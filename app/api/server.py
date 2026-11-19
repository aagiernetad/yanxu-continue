"""本地研究工作台 API：任务状态落库，执行单进程，WebSocket 可随时重连。"""
import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from app.agent import main_agent as agent_runtime
from app.api.context import set_run_context, reset_run_context, set_thread_context, reset_thread_context
from app.api.monitor import manager
from app.api.knowledge import router as knowledge_router
from app.api.storage import ACTIVE, BudgetExceeded, DATA_DIR, now, store
from app.utils.artifact_checker import inspect_artifacts

project_root = Path(__file__).resolve().parents[1]
output_dir = project_root / "output"
updated_dir = project_root / "updated"
active_tasks: dict[str, asyncio.Task] = {}
uploads_busy: set[str] = set()
deleting_sessions: set[str] = set()
logger = logging.getLogger(__name__)
MAX_ACTIVE_TASKS = max(1, int(os.getenv("MAX_ACTIVE_TASKS", "4")))
TASK_TIMEOUT_SECONDS = max(1, float(os.getenv("TASK_TIMEOUT_SECONDS", "600")))
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_ORIGINS = [origin.strip().rstrip("/") for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]


@contextmanager
def single_worker():
    """防止第二个 worker 把第一个 worker 的运行中任务误判为重启中断。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with (DATA_DIR / "server.lock").open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("当前任务调度仅支持单 worker；另一个服务已使用此数据目录") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


@asynccontextmanager
async def lifespan(_app):
    with single_worker():
        store.setup()
        store.recover()
        manager.set_loop(asyncio.get_running_loop())
        async with AsyncSqliteSaver.from_conn_string(str(DATA_DIR / "checkpoints.sqlite3")) as saver:
            await saver.setup()
            agent_runtime.main_agent = agent_runtime.build_main_agent(saver)
            try:
                yield
            finally:
                tasks = tuple(active_tasks.values())
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                for run_id in tuple(manager.pending):
                    await manager.drain(run_id)
                manager.loop = None


app = FastAPI(title="DeepAgents API", lifespan=lifespan)
app.include_router(knowledge_router)


@app.middleware("http")
async def limit_upload_body(request, call_next):
    if request.method == "POST" and request.url.path == "/api/upload":
        # 在 multipart 解析/临时落盘之前拦截过大的请求；本地浏览器上传均提供 Content-Length。
        length = request.headers.get("content-length", "")
        if not length.isdecimal():
            return JSONResponse({"detail": "上传需要有效的 Content-Length"}, status_code=411)
        if int(length) > 101 * 1024 * 1024:
            return JSONResponse({"detail": "上传请求不能超过 101 MB"}, status_code=413)
    return await call_next(request)


app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])


class TaskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    thread_id: str | None = None
    run_id: str | None = None  # 客户端生成，同时作为幂等键和聊天轮次 ID


class PlanDecision(BaseModel):
    run_id: str
    plan_version: int = Field(ge=1)
    action: Literal["approve", "revise"]
    feedback: str = Field(default="", max_length=4000)


def valid_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value):
        raise HTTPException(400, "无效的会话或任务 ID")
    return value


def session_available(thread_id: str):
    if thread_id in deleting_sessions:
        raise HTTPException(409, "会话正在删除，请稍后重试")


def run_directory(thread_id: str, run_id: str) -> Path:
    return output_dir / f"session_{valid_id(thread_id)}" / valid_id(run_id)


def run_files(thread_id, run_id):
    directory = run_directory(thread_id, run_id)
    run = store.get_run(run_id)
    inputs = json.loads(run["inputs"]) if run else []
    checked = inspect_artifacts(directory, inputs)
    files = []
    for item in checked["generated_files"]:
        path = directory / item["relative_path"]
        files.append({"name": path.name, "type": "file", "path": item["relative_path"],
                      "thread_id": thread_id, "run_id": run_id, "size": path.stat().st_size,
                      "mtime": path.stat().st_mtime})
    return sorted(files, key=lambda item: item["mtime"], reverse=True)


async def terminal(thread_id, run_id, event, message, result="", code=""):
    await manager.drain(run_id)
    try:
        store.set_files(run_id, run_files(thread_id, run_id))
    except OSError:
        pass  # 文件检查失败不能阻止任务进入终态
    await manager.send_to_thread({"type": "monitor_event", "event": event, "run_id": run_id,
                                  "message": message, "data": {"result": result, "code": code}, "timestamp": now()}, thread_id)


async def execute_task(query, thread_id, run_id, phase="execute"):
    run_token, thread_token = set_run_context(run_id), set_thread_context(thread_id)
    try:
        async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
            run = store.get_run(run_id)
            if phase == "plan":
                await manager.send_to_thread({"type": "monitor_event", "event": "task_accepted", "run_id": run_id,
                    "message": "正在生成研究计划", "data": {"query": query, "phase": "planning", "plan_version": run["plan_version"]}, "timestamp": now()}, thread_id)
                uploads = updated_dir / f"session_{thread_id}"
                names = [p.name for p in uploads.iterdir() if p.is_file() and not p.is_symlink() and not p.name.startswith(".upload-")] if uploads.exists() else []
                plan = await agent_runtime.plan_task(query, names, run["plan"], run["plan_feedback"])
                await manager.drain(run_id)
                await manager.send_to_thread({"type": "monitor_event", "event": "plan_ready", "run_id": run_id,
                    "message": "计划已生成，等待确认", "data": {"plan": plan, "plan_version": run["plan_version"]}, "timestamp": now()}, thread_id)
                return
            await manager.send_to_thread({"type": "monitor_event", "event": "plan_approved", "run_id": run_id,
                "message": "计划已确认，开始执行", "data": {"plan_version": run["plan_version"]}, "timestamp": now()}, thread_id)
            result = await agent_runtime.run_deep_agent(query, thread_id, run_id)
        await terminal(thread_id, run_id, "task_result", "任务执行完成", result)
    except asyncio.CancelledError:
        await terminal(thread_id, run_id, "task_cancelled", "任务已取消")
        raise
    except TimeoutError:
        await terminal(thread_id, run_id, "error", f"任务超过 {TASK_TIMEOUT_SECONDS:g} 秒，已停止等待")
    except BudgetExceeded as exc:
        await terminal(thread_id, run_id, "error", str(exc), code="budget_exceeded")
    except Exception:
        # 详细异常留在服务端，避免数据库地址、凭据或内部路径泄漏到浏览器。
        import traceback
        traceback.print_exc()
        await terminal(thread_id, run_id, "error", "任务执行失败，请查看服务端日志后重试")
    finally:
        reset_thread_context(thread_token)
        reset_run_context(run_token)


def forget_task(thread_id, run_id, task):
    if active_tasks.get(run_id) is task:
        active_tasks.pop(run_id, None)
    if not task.cancelled():
        task.exception()  # 消费异常，避免后台 Task exception was never retrieved
    run = store.get_run(run_id)
    if run and run["status"] in ("planning", "running", "cancelling") and run_id not in active_tasks:
        # create_task 之后、协程第一次执行之前取消，也必须有终态。
        manager.schedule({"type": "monitor_event", "thread_id": thread_id, "run_id": run_id,
                          "event": "task_cancelled" if task.cancelled() else "error",
                          "message": "任务已取消" if task.cancelled() else "任务异常结束",
                          "data": {}, "timestamp": now()})


def launch_task(query, thread_id, run_id, phase):
    task = asyncio.create_task(execute_task(query, thread_id, run_id, phase))
    active_tasks[run_id] = task
    task.add_done_callback(lambda finished: forget_task(thread_id, run_id, finished))


def has_capacity():
    return sum(not task.done() for task in active_tasks.values()) < MAX_ACTIVE_TASKS


@app.get("/api/sessions")
async def list_sessions(q: str = ""):
    return {"sessions": store.sessions(q[:200])}


@app.get("/api/sessions/{thread_id}")
async def get_session_history(thread_id: str):
    valid_id(thread_id)
    session_available(thread_id)
    history = store.history(thread_id)
    uploads = updated_dir / f"session_{thread_id}"
    history["uploads"] = [{"name": path.name, "size": path.stat().st_size}
                          for path in uploads.iterdir() if path.is_file() and not path.is_symlink() and not path.name.startswith(".upload-")] if uploads.exists() else []
    return history


def session_cleanup_paths(thread_id: str):
    """先核对全部绝对路径，再清理此会话目录，拒绝指向其他位置的链接。"""
    paths = []
    for base in (output_dir, updated_dir):
        base = base.resolve()
        path = base / f"session_{thread_id}"
        if path.is_symlink() or path.is_junction() or path.resolve() != path or not path.is_relative_to(base):
            raise HTTPException(409, "会话文件目录异常，无法自动删除")
        paths.append(path)
    return paths


def remove_session_files(paths):
    for path in paths:
        if path.exists():
            shutil.rmtree(path)


@app.delete("/api/sessions/{thread_id}")
async def delete_session(thread_id: str):
    valid_id(thread_id)
    session_available(thread_id)
    history = store.history(thread_id)
    if thread_id in uploads_busy:
        raise HTTPException(409, "会话正在上传文件，请等待上传完成再删除")
    if any(turn["status"] in ("planning", "running", "cancelling")
           or ((task := active_tasks.get(turn["id"])) is not None and not task.done())
           for turn in history["turns"]):
        raise HTTPException(409, "会话正在执行任务，请先取消任务再删除")
    paths = session_cleanup_paths(thread_id)
    # 此服务使用单 worker；在首次 await 前占用会话，阻止审批、提交或上传穿插。
    deleting_sessions.add(thread_id)
    try:
        for turn in history["turns"]:
            await manager.drain(turn["id"])
        await agent_runtime.main_agent.checkpointer.adelete_thread(thread_id)
        await asyncio.to_thread(remove_session_files, paths)
        store.delete_session(thread_id)
        await manager.session_deleted(thread_id)
        return {"status": "deleted", "thread_id": thread_id}
    except OSError as exc:
        logger.exception("会话清理失败: %s", thread_id)
        raise HTTPException(503, "会话清理未完成，请重试删除") from exc
    finally:
        deleting_sessions.discard(thread_id)


@app.post("/api/task")
async def run_task(request: TaskRequest):
    thread_id = valid_id(request.thread_id or str(uuid.uuid4()))
    session_available(thread_id)
    run_id = valid_id(request.run_id or str(uuid.uuid4()))
    query = request.query.strip()
    if not query:
        raise HTTPException(422, "请输入任务")
    previous = store.get_run(run_id)
    if previous:
        if previous["thread_id"] != thread_id or previous["query"] != query:
            raise HTTPException(409, "任务 ID 已被其他请求使用")
        return {"status": previous["status"], "thread_id": thread_id, "run_id": run_id}
    if thread_id in uploads_busy or store.active_run(thread_id):
        raise HTTPException(409, "当前会话正在执行任务或上传文件，请等待结束")
    if not has_capacity():
        raise HTTPException(429, "当前任务较多，请稍后重试")
    try:
        store.create_run(thread_id, run_id, query, status="planning")
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "当前会话已有活跃任务") from exc
    launch_task(query, thread_id, run_id, "plan")
    return {"status": "planning", "thread_id": thread_id, "run_id": run_id}


@app.post("/api/task/{thread_id}/plan")
async def decide_plan(thread_id: str, decision: PlanDecision):
    run = owned_run(thread_id, decision.run_id)
    if decision.action == "revise" and not decision.feedback.strip():
        raise HTTPException(422, "请填写计划修改意见")

    task = active_tasks.get(decision.run_id)
    if run["status"] == "waiting_approval" and task and not task.done():
        await asyncio.gather(asyncio.shield(task), return_exceptions=True)
        run = owned_run(thread_id, decision.run_id)
    if run["status"] == "waiting_approval" and run["plan_version"] == decision.plan_version and not has_capacity():
        raise HTTPException(429, "当前任务较多，计划已保留，请稍后确认")
    try:
        changed = store.decide_plan(decision.run_id, decision.plan_version, decision.action, decision.feedback.strip())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if changed:
        launch_task(run["query"], thread_id, decision.run_id, "execute" if decision.action == "approve" else "plan")
    current = store.get_run(decision.run_id)
    return {"status": current["status"], "thread_id": thread_id, "run_id": decision.run_id, "plan_version": current["plan_version"]}


@app.post("/api/task/{thread_id}/cancel")
async def cancel_task(thread_id: str, run_id: str):
    valid_id(thread_id)
    session_available(thread_id)
    run = store.get_run(valid_id(run_id))
    if not run or run["thread_id"] != thread_id:
        raise HTTPException(404, "任务不存在")
    if run["status"] not in ACTIVE:
        return {"status": run["status"], "thread_id": thread_id, "run_id": run_id}
    store.cancelling(run_id)
    task = active_tasks.get(run_id)
    if task and not task.done() and not task.cancelling():
        task.cancel()
    elif not task or task.done():
        await terminal(thread_id, run_id, "task_cancelled", "任务已取消")
    return {"status": store.get_run(run_id)["status"], "thread_id": thread_id, "run_id": run_id}


@app.post("/api/upload")
async def upload_files(files: list[UploadFile] = File(...), thread_id: str = Form(...)):
    valid_id(thread_id)
    session_available(thread_id)
    if thread_id in uploads_busy or store.active_run(thread_id):
        raise HTTPException(409, "任务执行或上传期间不能修改附件")
    if not 1 <= len(files) <= 8:
        raise HTTPException(400, "一次最多上传 8 个文件")
    names = [file.filename or "" for file in files]
    for name in names:
        # 同时排除 Windows 盘符、ADS、保留设备名和浏览器以外客户端构造的路径。
        if (not name or name.startswith(".upload-") or len(name) > 180 or name != Path(name).name or any(ch in name for ch in '/\\:<>"|?*')
                or name.endswith((".", " ")) or any(ord(ch) < 32 for ch in name)
                or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)):
            raise HTTPException(400, "文件名无效")
    if len(set(name.casefold() for name in names)) != len(names):
        raise HTTPException(400, "同一批文件名不能重复")
    target = updated_dir / f"session_{thread_id}"
    target.mkdir(parents=True, exist_ok=True)
    if any((target / name).exists() for name in names):
        raise HTTPException(409, "同名附件已存在，请修改文件名")
    uploads_busy.add(thread_id)
    temporary, saved = [], []
    try:
        for upload, name in zip(files, names):
            temp = target / f".upload-{uuid.uuid4().hex}"
            temporary.append(temp)
            size = 0
            with temp.open("xb") as stream:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "单个附件不能超过 25 MB")
                    await asyncio.to_thread(stream.write, chunk)
            if sum(p.stat().st_size for p in target.iterdir() if p.is_file()) > 100 * 1024 * 1024:
                raise HTTPException(413, "会话附件总大小不能超过 100 MB")
        for temp, name in zip(temporary, names):
            temp.replace(target / name)
            saved.append(target / name)
        return {"status": "uploaded", "files": names}
    except BaseException:
        for path in saved:
            path.unlink(missing_ok=True)
        raise
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)
        uploads_busy.discard(thread_id)
        for upload in files:
            await upload.close()


def owned_run(thread_id, run_id):
    session_available(thread_id)
    run = store.get_run(valid_id(run_id))
    if not run or run["thread_id"] != valid_id(thread_id):
        raise HTTPException(404, "任务不存在")
    return run


@app.get("/api/files")
async def list_files(thread_id: str, run_id: str):
    owned_run(thread_id, run_id)
    files = run_files(thread_id, run_id)
    store.set_files(run_id, files)
    return {"files": files, "revision": store.get_run(run_id)["revision"]}


@app.get("/api/download")
async def download_file(thread_id: str, run_id: str, path: str):
    owned_run(thread_id, run_id)
    directory = run_directory(thread_id, run_id).resolve()
    resolved = (directory / path).resolve()
    if Path(path).is_absolute() or not resolved.is_relative_to(directory):
        raise HTTPException(403, "文件超出本次任务目录")
    if path not in {item["path"] for item in run_files(thread_id, run_id)} or not resolved.is_file():
        raise HTTPException(404, "产物不存在")
    return FileResponse(resolved, filename=resolved.name)


@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", thread_id) or (websocket.headers.get("origin") and websocket.headers["origin"] not in ALLOWED_ORIGINS):
        await websocket.close(code=1008)
        return
    try:
        await manager.connect(websocket, thread_id)
        while True:
            await websocket.receive_text()
            await manager.pong(websocket, thread_id)
    except (WebSocketDisconnect, OSError, TimeoutError):
        pass
    finally:
        manager.disconnect(websocket, thread_id)


if __name__ == "__main__":
    uvicorn.run("app.api.server:app", host="127.0.0.1", port=8000, reload=True)
