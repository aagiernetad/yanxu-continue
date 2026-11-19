"""工具监控和 WebSocket 广播；任务账本是状态来源，连接只负责传输。"""
import asyncio
import builtins
import uuid
from typing import Any
from weakref import WeakValueDictionary

from fastapi import WebSocket

from app.api.context import get_run_context, get_thread_context, tool_call_context
from app.api.storage import now, store


class ToolMonitor:
    def __init__(self):
        self.websocket_manager = None

    def set_websocket_manager(self, connection_manager):
        self.websocket_manager = connection_manager

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None):
        payload = {"type": "monitor_event", "event": event_type, "message": message,
                   "data": data or {}, "timestamp": now(), "thread_id": get_thread_context(),
                   "run_id": get_run_context()}
        bound = self.websocket_manager
        if bound and bound.loop and not bound.loop.is_closed() and payload["thread_id"] and payload["run_id"]:
            try:
                bound.loop.call_soon_threadsafe(bound.schedule, payload)
            except RuntimeError:
                pass  # 服务关闭时迟到的同步工具不能重新启动事件循环。
        if hasattr(builtins, "runtime") and hasattr(builtins.runtime, "stream_writer"):
            try:
                builtins.runtime.stream_writer(payload)
            except Exception:
                pass
        if event_type != "answer_delta":
            print(f"[Monitor:{event_type}] {message}")

    def report_tool(self, tool_name, args=None):
        if tool_call_context.get() is not None:
            return  # 中间件已记录真实调用；工具内部仍可上报文件、检索等业务事件。
        self._emit("tool_start", f"开始执行工具: {tool_name}", {"tool_name": tool_name, "args": args})

    def report_assistant(self, assistant_name, args=None):
        self._emit("assistant_call", f"正在调用助手: {assistant_name}", {"assistant_name": assistant_name, "args": args})

    def report_task_result(self, result):
        self._emit("task_result", "任务执行完成", {"result": result})

    def report_task_cancelled(self):
        self._emit("task_cancelled", "任务已取消")

    def report_session_dir(self, path):
        self._emit("session_created", "工作目录已创建", {"path": path})


monitor = ToolMonitor()


class ConnectionManager:
    def __init__(self, storage=store):
        self.store = storage
        self.active_connections: dict[str, set[WebSocket]] = {}
        self.send_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self.pending: dict[str, set[asyncio.Task]] = {}
        self.loop = None

    def set_loop(self, loop):
        self.loop = loop
        monitor.set_websocket_manager(self)

    def get_send_lock(self, thread_id):
        return self.send_locks.setdefault(thread_id, asyncio.Lock())

    def schedule(self, payload):
        task = asyncio.create_task(self.send_to_thread(payload, payload["thread_id"]))
        pending = self.pending.setdefault(payload["run_id"], set())
        pending.add(task)
        def finished(done):
            pending.discard(done)
            if not pending and self.pending.get(payload["run_id"]) is pending:
                self.pending.pop(payload["run_id"], None)
            if not done.cancelled() and done.exception():
                print(f"[Monitor] 事件保存失败: {done.exception()}")
        task.add_done_callback(finished)

    async def drain(self, run_id):
        await asyncio.sleep(0)
        while self.pending.get(run_id):
            await asyncio.gather(*tuple(self.pending[run_id]), return_exceptions=True)
        self.pending.pop(run_id, None)

    async def connect(self, websocket, thread_id):
        await websocket.accept()
        async with self.get_send_lock(thread_id):
            self.active_connections.setdefault(thread_id, set()).add(websocket)
            for event in self.store.events(thread_id):
                await asyncio.wait_for(websocket.send_json({**event, "replayed": True}), 3)

    def disconnect(self, websocket, thread_id):
        connections = self.active_connections.get(thread_id)
        if connections:
            connections.discard(websocket)
            if not connections:
                self.active_connections.pop(thread_id, None)

    async def pong(self, websocket, thread_id):
        async with self.get_send_lock(thread_id):
            await asyncio.wait_for(websocket.send_json({"type": "pong", "message": "pong"}), 3)

    async def send_to_thread(self, message, thread_id):
        async with self.get_send_lock(thread_id):
            packet = self.store.record({**message, "thread_id": thread_id, "event_id": uuid.uuid4().hex})
            if packet is None:
                return
            async def send(websocket):
                try:
                    await asyncio.wait_for(websocket.send_json(packet), 3)
                except Exception:
                    self.disconnect(websocket, thread_id)
            await asyncio.gather(*(send(ws) for ws in tuple(self.active_connections.get(thread_id, ()))))

    async def session_deleted(self, thread_id):
        """通知仍打开该会话的标签页；删除通知不写回已清空的账本。"""
        async with self.get_send_lock(thread_id):
            async def send(websocket):
                try:
                    await asyncio.wait_for(websocket.send_json({"type": "session_deleted", "thread_id": thread_id}), 3)
                except Exception:
                    self.disconnect(websocket, thread_id)
            await asyncio.gather(*(send(ws) for ws in tuple(self.active_connections.get(thread_id, ()))))


manager = ConnectionManager()
