"""
Jev Passage Gate

负责根据 Jev evidence score，
对候选检索结果进行分级。

当前版本：
- strong evidence：高价值证据
- weak evidence：可能有帮助的辅助证据
- rejected：低价值结果

当前实验阈值：
- strong >= 0.80
- weak >= 0.40
- rejected < 0.40

Jev 调用失败时采用 fail-open：
不丢弃原始检索结果，而是降级为 weak evidence。

同时提供最小结果兜底：
如果 strong + weak 数量不足 MIN_KEEP，
则从 rejected 中按照 Tavily score 从高到低补足。

这样避免 Jev 过滤过强后，
Agent 因为“资料过少”再次触发额外搜索。
"""

from typing import Any

from app.utils.jev_client import evaluate_evidence


# Jev Evidence 分级阈值
STRONG_EVIDENCE_THRESHOLD = 0.80
WEAK_EVIDENCE_THRESHOLD = 0.40


# 最少保留多少条结果给后续 Agent
MIN_KEEP = 3


def _get_passage_text(item: dict[str, Any]) -> str:
    """
    从候选结果中提取用于 Jev 判断的文本。

    兼容：
    1. Tavily title
    2. Tavily raw_content
    3. Tavily content
    4. 测试数据 text

    优先使用 raw_content；
    如果没有，则使用 content / text。

    最终组合 title + content，
    给 Jev 更完整的语义上下文。
    """

    title = item.get("title") or ""

    content = (
        item.get("raw_content")
        or item.get("content")
        or item.get("text")
        or ""
    )

    if title and content:
        return (
            f"Title: {title}\n\n"
            f"Content: {content}"
        )

    return title or content


def filter_passages(
    query: str,
    passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    根据 Jev evidence score 对候选 passage 进行三级分类。

    如果 strong + weak 不足 MIN_KEEP，
    则从 rejected 中按照 Tavily score 补足。

    返回：

    {
        "strong_evidence": [...],
        "weak_evidence": [...],
        "rejected": [...],

        "stats": {
            "total": ...,
            "strong": ...,
            "weak": ...,
            "rejected": ...,
            "fallback_added": ...,
            "degraded": ...,
            "min_keep": ...,
            "strong_threshold": ...,
            "weak_threshold": ...
        }
    }
    """

    strong_evidence = []
    weak_evidence = []
    rejected = []

    # 是否出现 Jev 调用异常
    degraded = False

    for item in passages:

        text = _get_passage_text(item)

        # 完全没有可判断内容
        if not text.strip():

            rejected.append(
                {
                    **item,
                    "_jev_score": 0.0,
                    "_evidence_level": "rejected",
                    "_gate_reason": "empty_passage",
                }
            )

            continue

        # 调用 Jev 判断证据价值
        score = evaluate_evidence(
            query=query,
            passage=text,
        )

        # Jev 网络异常、超时等
        #
        # fail-open：
        # 不直接删除结果，
        # 但也不能认为它是 strong evidence。
        if score is None:

            degraded = True

            weak_evidence.append(
                {
                    **item,
                    "_jev_score": None,
                    "_evidence_level": "weak",
                    "_gate_reason": "jev_failed_keep",
                }
            )

            continue

        # Strong Evidence
        if score >= STRONG_EVIDENCE_THRESHOLD:

            strong_evidence.append(
                {
                    **item,
                    "_jev_score": score,
                    "_evidence_level": "strong",
                    "_gate_reason": "strong_evidence",
                }
            )

        # Weak Evidence
        elif score >= WEAK_EVIDENCE_THRESHOLD:

            weak_evidence.append(
                {
                    **item,
                    "_jev_score": score,
                    "_evidence_level": "weak",
                    "_gate_reason": "weak_evidence",
                }
            )

        # Rejected
        else:

            rejected.append(
                {
                    **item,
                    "_jev_score": score,
                    "_evidence_level": "rejected",
                    "_gate_reason": "low_evidence",
                }
            )

    # Strong 按 Jev score 从高到低
    strong_evidence.sort(
        key=lambda x: (
            x["_jev_score"]
            if x["_jev_score"] is not None
            else -1
        ),
        reverse=True,
    )

    # Weak 按 Jev score 从高到低
    weak_evidence.sort(
        key=lambda x: (
            x["_jev_score"]
            if x["_jev_score"] is not None
            else -1
        ),
        reverse=True,
    )

    # --------------------------------------------------
    # 最小结果兜底
    # --------------------------------------------------

    current_keep = (
        len(strong_evidence)
        + len(weak_evidence)
    )

    need_fallback = max(
        0,
        MIN_KEEP - current_keep,
    )

    fallback_added = 0

    if need_fallback > 0:

        # 只允许真正的 low_evidence 参与兜底。
        # empty_passage 不应该重新捞回来。
        fallback_candidates = [
            item
            for item in rejected
            if item.get("_gate_reason") == "low_evidence"
        ]

        # 按 Tavily 原始相关性得分排序
        fallback_candidates.sort(
            key=lambda x: (
                x.get("score")
                if x.get("score") is not None
                else -1
            ),
            reverse=True,
        )

        selected_fallback = (
            fallback_candidates[:need_fallback]
        )

        selected_ids = {
            id(item)
            for item in selected_fallback
        }

        # 从 rejected 中删除已经被兜底选中的结果
        rejected = [
            item
            for item in rejected
            if id(item) not in selected_ids
        ]

        # 作为 weak evidence 返回给后续 Agent
        for item in selected_fallback:

            weak_evidence.append(
                {
                    **item,
                    "_evidence_level": "fallback",
                    "_gate_reason": "min_keep_fallback",
                }
            )

        fallback_added = len(
            selected_fallback
        )

    # Weak 最终重新排序：
    #
    # 正常 Jev weak 优先，
    # fallback 排在后面。
    weak_evidence.sort(
        key=lambda x: (
            0
            if x.get("_gate_reason")
            != "min_keep_fallback"
            else 1,
            -(
                x["_jev_score"]
                if x["_jev_score"] is not None
                else -1
            ),
        )
    )

    return {
        "strong_evidence": strong_evidence,

        "weak_evidence": weak_evidence,

        "rejected": rejected,

        "stats": {
            "total": len(passages),

            "strong": len(strong_evidence),

            "weak": len(weak_evidence),

            "rejected": len(rejected),

            "fallback_added": fallback_added,

            "degraded": degraded,

            "min_keep": MIN_KEEP,

            "strong_threshold":
                STRONG_EVIDENCE_THRESHOLD,

            "weak_threshold":
                WEAK_EVIDENCE_THRESHOLD,
        },
    }
