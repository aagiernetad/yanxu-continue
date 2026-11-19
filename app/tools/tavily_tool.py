"""
Tavily 网络搜索工具模块

封装 internet_search 工具，供网络搜索子智能体检索互联网公开信息。

当前流程：

Network Search Agent
        ↓
internet_search
        ↓
Tavily
        ↓
Jev Passage Gate
        ↓
Strong + Weak + Fallback
        ↓
返回给 Agent

Jev 负责减少低价值检索结果进入后续 LLM 上下文。
"""

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.tools import tool
from tavily import TavilyClient

from app.api.monitor import monitor
from app.utils.passage_gate import filter_passages


load_dotenv()


# TavilyClient 模块级复用，
# 避免每次工具调用重复初始化
tavily_client = TavilyClient(
    api_key=os.getenv("TAVILY_API_KEY")
)


@tool
def internet_search(
    query: str,
    research_goal: str,
    topic: Literal[
        "news",
        "finance",
        "general",
    ] = "general",
    max_results: int = 5,
    include_raw_content: bool = False,
):
    """
    根据研究目标检索互联网公开信息。

    本工具首先使用 Tavily 搜索，
    然后使用 Jev Evidence Gate 对搜索结果进行证据价值分级，
    只将 Strong Evidence、Weak Evidence 以及必要的兜底结果
    返回给网络搜索子智能体。

    注意：
    本工具只用于外部公开网页、新闻、政策等信息，
    不用于查询业务数据库或 RAGFlow 私有知识库。

    :param query:
        本次实际发送给 Tavily 的搜索关键词或自然语言问题。

    :param research_goal:
        当前搜索所服务的更高层研究目标。
        不要简单复制 query。
        应描述本次搜索最终希望解决的研究问题，
        Jev 会根据该目标判断搜索结果是否具有证据价值。

    :param topic:
        搜索主题，可选 news、finance、general。

    :param max_results:
        Tavily 返回的最大结果数。

    :param include_raw_content:
        是否返回网页原文内容。
        False 返回摘要，
        True 尝试返回更完整正文。

    :return:
        经 Jev Evidence Gate 筛选后的 Tavily 结构化搜索结果。
    """

    # --------------------------------------------------
    # 1. 上报工具调用信息
    # --------------------------------------------------

    monitor.report_tool(
        tool_name="网络搜索工具",
        args={
            "query": query,
            "research_goal": research_goal,
            "topic": topic,
            "max_results": max_results,
            "include_raw_content": include_raw_content,
        },
    )

    # --------------------------------------------------
    # 2. Tavily 搜索
    # --------------------------------------------------

    search_result = tavily_client.search(
        query=query,
        topic=topic,
        max_results=max_results,
        include_raw_content=include_raw_content,
    )

    # --------------------------------------------------
    # 3. 获取 Tavily results
    # --------------------------------------------------

    results = search_result.get(
        "results",
        [],
    )

    # Tavily 没有返回结果时，
    # 直接保持原结构返回。
    if not results:
        return search_result

    # --------------------------------------------------
    # 4. Jev Evidence Gate
    # --------------------------------------------------

    try:

        gated = filter_passages(
            query=research_goal,
            passages=results,
        )
        print(
            "[Jev Gate]",
            {
                "query": query,
                "research_goal": research_goal,
                "stats": gated["stats"],
         },
        )
    except Exception as exc:

        # Integration-level fail-open：
        #
        # 即使 passage_gate 本身出现意外异常，
        # 也不能导致整个 internet_search 工具失败。
        print(
            "[Jev] passage gate failed:",
            type(exc).__name__,
            exc,
        )

        return search_result

    # --------------------------------------------------
    # 5. 组合最终返回结果
    # --------------------------------------------------

    strong_evidence = gated[
        "strong_evidence"
    ]

    weak_evidence = gated[
        "weak_evidence"
    ]

    # Strong 在前，
    # Weak / fallback 在后。
    filtered_results = (
        strong_evidence
        +
        weak_evidence
    )

    # --------------------------------------------------
    # 6. 保持 Tavily 原始顶层结构
    # --------------------------------------------------

    filtered_search_result = {
        **search_result,

        # 用 Jev 过滤后的结果覆盖原 results
        "results": filtered_results,

        # 增加少量 Gate 统计信息，
        # 方便后续 trace / evaluation 分析
        "_jev_gate": gated["stats"],
    }

    return filtered_search_result
