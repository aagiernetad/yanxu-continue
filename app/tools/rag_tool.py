
"""
RAG 知识库检索工具。

将RAGPipeline 封装成 LangChain Tool，
供 DeepSearch Agent 调用。
"""

import asyncio
from pathlib import Path

from langchain_core.tools import tool

from app.api.monitor import monitor
from app.rag.rag_pipeline import RAGPipeline


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# RAG 数据库路径
DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "knowledge_base"
    / "vectors.db"
)


def _retrieve_knowledge(query: str) -> str:
    """
    执行同步 RAG 检索。

    不调用 LLM 生成最终回答，
    只返回检索证据。
    """

    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"RAG 数据库不存在: {DB_PATH}"
        )

    # 实例化已有的 RAG Pipeline
    pipeline = RAGPipeline(
        db_path=DB_PATH
    )

    # Dense Retrieval + Rerank
    results = pipeline.retrieve_reranked(
        query=query,
        candidate_k=10,
        top_n=5,
        score_threshold=0.4,
    )

    if not results:
        return (
            "知识库未检索到足够相关的证据。"
            "这不代表整份知识库一定没有答案。"
        )

    evidence_list = []

    for index, item in enumerate(results, start=1):

        source = item.get("source") or "未知文档"
        page = item.get("page")
        chunk_id = item.get("chunk_id", "")

        content = (
            item.get("text")
            or item.get("content")
            or ""
        )

        evidence = (
            f"[{index}]\n"
            f"来源文档：{source}\n"
            f"页码：{page if page is not None else '未知'}\n"
            f"Chunk ID：{chunk_id}\n"
            f"原始内容：\n{content}"
        )

        evidence_list.append(evidence)

    return (
        "知识库检索结果：\n\n"
        + "\n\n".join(evidence_list)
    )


@tool
async def search_knowledge_base(query: str) -> str:
    """
    检索已经索引的技术文档知识库。


    返回相关原文、文档来源及页码。
    """

    # 向现有 Monitor 上报工具调用
    monitor.report_tool(
        tool_name="search_knowledge_base",
        args={"query": query},
    )

    # 将同步检索放到线程中执行
    return await asyncio.to_thread(
        _retrieve_knowledge,
        query,
    )
