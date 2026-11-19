"""执行链负责预占预算和观测；Monitor 继续负责把事件交给存储/推送链路。"""
import asyncio
import time
from contextlib import contextmanager

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage, ToolMessage

from app.api import storage
from app.api.context import get_run_context, tool_call_context
from app.api.monitor import monitor


@contextmanager
def observe(kind, agent_name, tool_name="", call_id=""):
    run_id = get_run_context()
    if run_id:
        storage.store.reserve(run_id, kind, tool_name)
    details = {"agent_name": agent_name, "tool_name": tool_name, "tool_call_id": call_id}
    label = tool_name or agent_name
    started = time.monotonic()
    monitor._emit(f"{kind}_start", f"开始调用：{label}", {**details})
    try:
        yield details
    except asyncio.CancelledError:
        details["status"] = "cancelled"
        raise
    except Exception as exc:
        details.update(status="error", error_type=type(exc).__name__)
        raise
    except BaseException as exc:
        details.update(status="interrupted", error_type=type(exc).__name__)
        raise
    finally:
        details.setdefault("status", "success")
        monitor._emit(f"{kind}_end", f"调用结束：{label}（{details['status']}）",
                      {**details, "duration_ms": round((time.monotonic() - started) * 1000)})


class ExecutionMiddleware(AgentMiddleware):
    def __init__(self, agent_name):
        self.agent_name = agent_name

    @staticmethod
    def with_search_budget(request):
        run_id = get_run_context()
        budget = storage.store.get_search_budget(run_id) if run_id else None
        if budget is None:
            return request
        instructions = (
            f"\n【本轮共享搜索额度】已使用 {budget['used']}/{budget['limit']} 次，"
            f"剩余 {budget['remaining']} 次 internet_search。"
            "此额度由主 Agent 和所有子 Agent 共享，多次委派不会重置。"
            "仅为影响核心结论的明确证据缺口搜索，复用已有来源；资料足够就停止，不必用完额度。"
        )
        if budget["remaining"] == 0:
            instructions += (
                "搜索额度已用尽，不得再调用 internet_search，也不得为继续联网搜索而重新委派。"
                "根据已有证据整理结果，继续必要的文件生成和评审；"
                "明确说明搜索次数受限、未验证的结论和未完成的要求，不得编造或声称全部完成。"
            )
        message = request.system_message
        if message is None:
            message = SystemMessage(content=instructions)
        else:
            content = message.content
            content = content + instructions if isinstance(content, str) else [*content, {"type": "text", "text": instructions}]
            message = message.model_copy(update={"content": content})
        # 仅覆盖本次模型输入，不把会过期的额度写入持久对话历史。
        return request.override(system_message=message)

    def wrap_model_call(self, request, handler):
        with observe("model", self.agent_name):
            return handler(self.with_search_budget(request))

    async def awrap_model_call(self, request, handler):
        with observe("model", self.agent_name):
            return await handler(self.with_search_budget(request))

    @contextmanager
    def tool_scope(self, request):
        call = request.tool_call
        with observe("tool", self.agent_name, call["name"], call["id"]) as details:
            token = tool_call_context.set(call["id"])
            try:
                yield details
            finally:
                tool_call_context.reset(token)

    @staticmethod
    def classify(result, details):
        # 兼容现有字符串工具；异常与已知业务错误均不能算成功。不记录完整返回正文。
        content = getattr(result, "content", result)
        if getattr(result, "status", "") == "error" or (isinstance(content, str) and content.startswith(("错误", "转换失败", "查询失败", "操作被拒绝"))):
            details["status"] = "error"
        return result

    def search_limit_result(self, request, exc):
        call = request.tool_call
        if exc.kind != "search" or call["name"] != "internet_search":
            raise exc
        # 预占失败，实际工具未执行，也不增加搜索或工具计数。并发调用仍由账本原子限流。
        message = (
            f"本轮联网搜索次数已达上限（{exc.used}/{exc.limit}），本次搜索未执行。"
            "不要再次调用 internet_search 或通过重新委派继续搜索。"
            "请基于已获得的证据总结并返回主 Agent；说明搜索受限和证据缺口，"
            "由主 Agent 继续必要的文件生成和评审，不得编造未检索到的内容。"
        )
        monitor._emit("search_budget_exhausted", "联网搜索次数已达上限，正在整理已有资料", {
            "agent_name": self.agent_name, "tool_name": call["name"], "tool_call_id": call["id"],
            "used": exc.used, "limit": exc.limit,
        })
        return ToolMessage(content=message, tool_call_id=call["id"], name=call["name"], status="error")

    def wrap_tool_call(self, request, handler):
        try:
            with self.tool_scope(request) as details:
                return self.classify(handler(request), details)
        except storage.BudgetExceeded as exc:
            return self.search_limit_result(request, exc)

    async def awrap_tool_call(self, request, handler):
        try:
            with self.tool_scope(request) as details:
                return self.classify(await handler(request), details)
        except storage.BudgetExceeded as exc:
            return self.search_limit_result(request, exc)
