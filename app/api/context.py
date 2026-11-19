"""
请求上下文管理模块

负责在异步请求链路中保存当前任务的 thread_id 和 session_dir
工具、智能体和监控模块可以在深层调用中读取这些值，而不需要层层传参
"""

from contextvars import ContextVar, Token
from typing import Optional

# ContextVar 是协程级上下文变量，适合 FastAPI 这类异步 Web 服务
# 它可以避免多个并发请求共用全局变量时出现 thread_id 或 session_dir 串台
_session_dir_ctx: ContextVar[Optional[str]] = ContextVar(
    "session_dir",
    default=None,
)
_thread_id_ctx: ContextVar[Optional[str]] = ContextVar(
    "thread_id",
    default=None,
)
_run_id_ctx: ContextVar[Optional[str]] = ContextVar("run_id", default=None)
_input_files_ctx: ContextVar[tuple[str, ...]] = ContextVar("input_files", default=())
tool_call_context: ContextVar[Optional[str]] = ContextVar("tool_call_context", default=None)


def get_run_context() -> Optional[str]:
    return _run_id_ctx.get()


def set_run_context(run_id: str):
    return _run_id_ctx.set(run_id)


def reset_run_context(token):
    _run_id_ctx.reset(token)


def get_input_files() -> tuple[str, ...]:
    return _input_files_ctx.get()


def set_input_files(names):
    return _input_files_ctx.set(tuple(names))


def reset_input_files(token):
    _input_files_ctx.reset(token)


def set_session_context(path: str) -> Token[Optional[str]]:
    """
    设置当前请求链路的会话目录

    :param path: 当前任务的工作目录
    :return: reset 时需要使用的上下文 token
    """
    return _session_dir_ctx.set(path)


def get_session_context() -> Optional[str]:
    """
    获取当前请求链路的会话目录

    :return: 当前任务工作目录；未设置时返回 None
    """
    return _session_dir_ctx.get()


def set_thread_context(thread_id: str) -> Token[Optional[str]]:
    """
    设置当前请求链路的线程 ID

    :param thread_id: 前端连接和 Agent 检查点共用的会话 ID；单轮任务由 run_id 标识
    :return: reset 时需要使用的上下文 token
    """
    return _thread_id_ctx.set(thread_id)


def get_thread_context() -> Optional[str]:
    """
    获取当前请求链路的线程 ID

    :return: 当前会话 ID；未设置时返回 None
    """
    return _thread_id_ctx.get()


def reset_thread_context(token):
    _thread_id_ctx.reset(token)


def reset_session_context(
    session_token: Token[Optional[str]],
    thread_token: Optional[Token[Optional[str]]] = None,
) -> None:
    """
    恢复请求上下文，避免本次任务信息残留到后续请求

    :param session_token: set_session_context 返回的 token
    :param thread_token: set_thread_context 返回的 token
    """
    _session_dir_ctx.reset(session_token)
    if thread_token is not None:
        _thread_id_ctx.reset(thread_token)
