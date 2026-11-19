"""本地单进程服务的任务账本；SQLite 保存聊天、终态和最近事件，不保存密钥。"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ACTIVE = ("planning", "waiting_approval", "running", "cancelling")
TERMINAL = {"task_result": "completed", "task_cancelled": "cancelled", "error": "failed"}
DATA_DIR = Path(os.getenv("DEEPSEARCH_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BudgetExceeded(RuntimeError):
    """带类别的调用限制；搜索可停止检索后收尾，其余限制由 API 明确报错。"""

    def __init__(self, kind: str, used: int, limit: int):
        self.kind, self.used, self.limit = kind, used, limit
        super().__init__(f"任务调用预算已用尽（{kind}: {used}/{limit}）")


class SessionStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def setup(self):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
                    query TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    files TEXT NOT NULL DEFAULT '[]', inputs TEXT NOT NULL DEFAULT '[]',
                    revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(thread_id)
                    WHERE status IN ('running', 'cancelling');
                CREATE INDEX IF NOT EXISTS run_history ON runs(thread_id, created_at);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_history ON events(thread_id, seq);
            """)
            if "revision" not in {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}:
                conn.execute("ALTER TABLE runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
            for name, definition in {
                "plan": "TEXT NOT NULL DEFAULT ''", "plan_version": "INTEGER NOT NULL DEFAULT 1",
                "approved_version": "INTEGER NOT NULL DEFAULT 0", "plan_feedback": "TEXT NOT NULL DEFAULT ''",
                "usage": "TEXT NOT NULL DEFAULT '{}'", "budget": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
            conn.execute("DROP INDEX IF EXISTS one_active_run")
            conn.execute("CREATE UNIQUE INDEX one_active_run ON runs(thread_id) WHERE status IN ('planning','waiting_approval','running','cancelling')")

    def get_run(self, run_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def get_search_budget(self, run_id: str):
        """读取整轮共享的实时搜索额度；独立 CLI 未建账本时不额外施加限制。"""
        if not self.path.is_file():
            return None
        run = self.get_run(run_id)
        if not run:
            return None
        usage, budget = json.loads(run["usage"]), json.loads(run["budget"])
        if "search" not in budget:
            return None
        used, limit = usage.get("search", 0), budget["search"]
        return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

    def active_run(self, thread_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE thread_id=? AND status IN ('planning','waiting_approval','running','cancelling')", (thread_id,)).fetchone()
        return dict(row) if row else None

    def create_run(self, thread_id: str, run_id: str, query: str, status="running"):
        stamp = now()
        budget = {kind: max(1, int(os.getenv(env, default))) for kind, env, default in (
            ("model", "MAX_MODEL_CALLS", "40"), ("tool", "MAX_TOOL_CALLS", "50"),
            ("search", "MAX_SEARCH_CALLS", "5"), ("delegate", "MAX_DELEGATIONS", "8"),
        )}
        with self.connect() as conn:
            conn.execute("INSERT INTO runs(run_id,thread_id,query,status,created_at,updated_at,budget) VALUES(?,?,?,?,?,?,?)", (run_id, thread_id, query, status, stamp, stamp, json.dumps(budget)))

    def decide_plan(self, run_id, version, action, feedback=""):
        """比较版本并原子转换状态；重试不能重复执行或重复增加计划版本。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise ValueError("任务不存在")
            if action == "approve" and row["approved_version"] == version:
                return False
            if action == "revise" and row["plan_version"] == version + 1 and row["plan_feedback"] == feedback:
                return False
            if row["status"] != "waiting_approval" or row["plan_version"] != version:
                raise ValueError("计划已变化或已处理，请刷新后再操作")
            if action == "approve":
                conn.execute("UPDATE runs SET status='running',approved_version=?,revision=revision+1,updated_at=? WHERE run_id=?", (version, now(), run_id))
            elif action == "revise" and feedback.strip():
                conn.execute("UPDATE runs SET status='planning',plan_version=plan_version+1,plan_feedback=?,revision=revision+1,updated_at=? WHERE run_id=?", (feedback, now(), run_id))
            else:
                raise ValueError("请填写计划修改意见")
        return True

    def reserve(self, run_id, kind, tool_name=""):
        """调用前原子预占；计数跨主子 Agent、计划修改及审批持续累积。"""
        if not self.path.is_file():
            return
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,usage,budget FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:  # 兼容独立 CLI/评测入口，不存在 API 账本时不套用业务预算。
                return
            if row["status"] not in ("planning", "running") or (kind == "tool" and row["status"] != "running"):
                raise RuntimeError("当前任务阶段不允许执行此调用")
            usage, budget = json.loads(row["usage"]), json.loads(row["budget"])
            keys = [kind]
            if kind == "tool" and tool_name in ("internet_search", "task"):
                keys.append("search" if tool_name == "internet_search" else "delegate")
            for key in keys:
                if key in budget and usage.get(key, 0) >= budget[key]:
                    raise BudgetExceeded(key, usage.get(key, 0), budget[key])
            for key in keys:
                usage[key] = usage.get(key, 0) + 1
            conn.execute("UPDATE runs SET usage=?,revision=revision+1 WHERE run_id=?", (json.dumps(usage), run_id))

    def set_inputs(self, run_id: str, names: list[str]):
        with self.connect() as conn:
            conn.execute("UPDATE runs SET inputs=? WHERE run_id=?", (json.dumps(names, ensure_ascii=False), run_id))

    def set_files(self, run_id: str, files: list[dict]):
        encoded = json.dumps(files, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute("UPDATE runs SET files=?,revision=revision+1 WHERE run_id=? AND files<>?", (encoded, run_id, encoded))

    def cancelling(self, run_id: str):
        with self.connect() as conn:
            conn.execute("UPDATE runs SET status='cancelling',updated_at=?,revision=revision+1 WHERE run_id=? AND status IN ('planning','waiting_approval','running')", (now(), run_id))

    def record(self, packet: dict):
        """终态和终态事件同一事务提交；迟到的工具事件、重复终态直接丢弃。"""
        run_id, event = packet["run_id"], packet["event"]
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,revision,plan_version FROM runs WHERE run_id=? AND thread_id=?", (run_id, packet["thread_id"])).fetchone()
            if not row or row["status"] not in ACTIVE:
                return None
            if event == "plan_ready":
                data = packet.get("data", {})
                if row["status"] != "planning" or data.get("plan_version") != row["plan_version"]:
                    return None
                conn.execute("UPDATE runs SET status='waiting_approval',plan=? WHERE run_id=?", (data["plan"], run_id))
            packet = {**packet, "revision": row["revision"] + 1}
            conn.execute("UPDATE runs SET revision=revision+1,updated_at=? WHERE run_id=?", (now(), run_id))
            if event in TERMINAL:
                conn.execute("UPDATE runs SET status=?,result=CASE WHEN ?='task_result' THEN ? ELSE result END,error=?,updated_at=? WHERE run_id=?", (
                    TERMINAL[event], event, packet.get("data", {}).get("result", ""),
                    packet["message"] if event == "error" else "", now(), run_id,
                ))
            # Token 不逐条落库；历史以最终正文/最近的正文快照为准，避免每个 token 写一次 SQLite。
            if event == "answer_delta":
                conn.execute("UPDATE runs SET result=? WHERE run_id=?", (packet["data"]["result"], run_id))
                return packet
            cursor = conn.execute("INSERT INTO events(run_id,thread_id,payload) VALUES(?,?,?)", (run_id, packet["thread_id"], json.dumps(packet, ensure_ascii=False)))
            packet = {**packet, "seq": cursor.lastrowid}
            conn.execute("DELETE FROM events WHERE run_id=? AND seq NOT IN (SELECT seq FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 120)", (run_id, run_id))
        return packet

    def events(self, thread_id: str, run_id: str | None = None):
        with self.connect() as conn:
            if run_id:
                rows = conn.execute("SELECT seq,payload FROM events WHERE thread_id=? AND run_id=? ORDER BY seq", (thread_id, run_id)).fetchall()
            else:
                rows = conn.execute("SELECT seq,payload FROM (SELECT seq,payload FROM events WHERE thread_id=? ORDER BY seq DESC LIMIT 120) ORDER BY seq", (thread_id,)).fetchall()
        return [{**json.loads(row["payload"]), "seq": row["seq"]} for row in rows]

    def history(self, thread_id: str):
        with self.connect() as conn:
            conn.execute("BEGIN")
            rows = conn.execute("SELECT * FROM runs WHERE thread_id=? ORDER BY created_at, rowid", (thread_id,)).fetchall()
            event_rows = conn.execute("SELECT run_id,seq,payload FROM events WHERE thread_id=? ORDER BY seq", (thread_id,)).fetchall()
        grouped = {}
        for event in event_rows:
            grouped.setdefault(event["run_id"], []).append({**json.loads(event["payload"]), "seq": event["seq"]})
        turns = [{
            "id": row["run_id"], "run_id": row["run_id"], "content": row["query"],
            "revision": row["revision"],
            "status": row["status"], "isRunning": row["status"] in ACTIVE,
            "result": row["result"] or row["error"] or ("任务已取消" if row["status"] == "cancelled" else ""),
            "timestamp": row["created_at"], "files": json.loads(row["files"]),
            "plan": row["plan"], "planVersion": row["plan_version"],
            "usage": json.loads(row["usage"]), "budget": json.loads(row["budget"]),
            "events": grouped.get(row["run_id"], []),
        } for row in rows]
        active = next((turn["id"] for turn in turns if turn["isRunning"]), None)
        return {"thread_id": thread_id, "turns": turns, "is_running": bool(active), "active_run_id": active}

    def delete_session(self, thread_id: str):
        """删除整段会话及事件；运行中的会话必须先停止。"""
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM runs WHERE thread_id=? AND status IN ('planning','running','cancelling')", (thread_id,)).fetchone():
                raise ValueError("会话正在执行任务，请先取消任务再删除")
            conn.execute("DELETE FROM events WHERE thread_id=?", (thread_id,))
            conn.execute("DELETE FROM runs WHERE thread_id=?", (thread_id,))

    def sessions(self, query: str = ""):
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT r.thread_id, MIN(r.created_at) AS created_at, MAX(r.updated_at) AS updated_at,
                    (SELECT query FROM runs q WHERE q.thread_id=r.thread_id ORDER BY created_at,rowid LIMIT 1) AS title,
                    MAX(CASE WHEN r.status IN ('planning','waiting_approval','running','cancelling') THEN 1 ELSE 0 END) AS is_running,
                    MIN(CASE WHEN r.status IN ('planning','running','cancelling') THEN 0 ELSE 1 END) AS can_delete
                FROM runs r GROUP BY r.thread_id
                HAVING ?='' OR EXISTS (SELECT 1 FROM runs s WHERE s.thread_id=r.thread_id AND instr(s.query,?)>0)
                ORDER BY updated_at DESC LIMIT 100
            """, (query, query)).fetchall()
        return [dict(row) for row in rows]

    def recover(self):
        """重启不自动重做外部工具；明确标记中断，允许用户开始下一轮。"""
        with self.connect() as conn:
            rows = conn.execute("SELECT run_id,thread_id FROM runs WHERE status IN ('planning','running','cancelling')").fetchall()
        for row in rows:
            self.record({"type": "monitor_event", "event": "error", "event_id": f"interrupted-{row['run_id']}",
                         "thread_id": row["thread_id"], "run_id": row["run_id"], "timestamp": now(),
                         "message": "服务重启，上一任务已中断。可重新发起研究。", "data": {}})


store = SessionStore(DATA_DIR / "sessions.sqlite3")
