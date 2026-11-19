"""浏览已有知识库：只读 SQLite，不初始化索引或调用模型服务。"""

import hashlib
import logging
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge_base" / "vectors.db"
router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


def source_id(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@contextmanager
def read_index():
    if not DB_PATH.is_file():
        yield None
        return
    try:
        with closing(sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            try:
                yield conn
            finally:
                conn.rollback()
    except sqlite3.Error as exc:
        logger.exception("读取知识库失败")
        raise HTTPException(503, "知识库暂时无法读取，请稍后重试") from exc


@router.get("/documents")
def list_documents():
    with read_index() as conn:
        rows = conn.execute("""
            SELECT source, COUNT(*) AS chunk_count, COUNT(DISTINCT page) AS page_count
            FROM chunks GROUP BY source ORDER BY source COLLATE NOCASE, source
        """).fetchall() if conn is not None else []
    documents = [{"id": source_id(row["source"]), **dict(row)} for row in rows]
    return {"documents": documents, "total_documents": len(documents),
            "total_chunks": sum(item["chunk_count"] for item in documents)}


@router.get("/documents/{document_id}/chunks")
def document_chunks(document_id: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50)):
    with read_index() as conn:
        if conn is None:
            raise HTTPException(404, "文档不存在或已移出知识库")
        sources = conn.execute("SELECT DISTINCT source FROM chunks").fetchall()
        source = next((row["source"] for row in sources if source_id(row["source"]) == document_id), None)
        if source is None:
            raise HTTPException(404, "文档不存在或已移出知识库")
        total = conn.execute("SELECT COUNT(*) FROM chunks WHERE source=?", (source,)).fetchone()[0]
        rows = conn.execute("""
            SELECT id, text, page, start_char, end_char FROM chunks WHERE source=?
            ORDER BY page, COALESCE(start_char, 0), COALESCE(end_char, 0), id LIMIT ? OFFSET ?
        """, (source, limit, offset)).fetchall()
    return {"document_id": document_id, "source": source, "total": total,
            "offset": offset, "limit": limit, "chunks": [dict(row) for row in rows]}
