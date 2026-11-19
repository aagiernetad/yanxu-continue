"""
Jev 客户端封装

当前阶段只负责：
1. 从 .env 读取 TYPESAFE_API_KEY
2. 复用 TypeSafeClient
3. 对 query + passage 做证据有效性判断
4. Jev 调用失败时返回 None，不让上层搜索直接报错
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from typesafe_sdk import Noul, TypeSafeClient


load_dotenv()


@lru_cache(maxsize=1)
def get_jev_client() -> TypeSafeClient | None:
    """
    获取并复用 Jev 客户端。

    如果没有配置 TYPESAFE_API_KEY，则返回 None。
    """
    if not os.getenv("TYPESAFE_API_KEY"):
        return None

    return TypeSafeClient()


def evaluate_evidence(
    query: str,
    passage: str,
) -> float | None:
    """
    判断 passage 是否包含能够回答 query 的有效证据。

    返回：
        0~1：Jev 给出的 evidence score
        None：Jev 未配置或调用失败
    """
    client = get_jev_client()

    if client is None:
        return None

    if not query.strip() or not passage.strip():
        return 0.0

    try:
        response = client.system_one(
            state={
                "query": query,
                "passage": passage,
            },
            questions={
                "evidence": Noul(
                    instructions=(
                        "Does the passage contain useful and direct evidence "
                        "for answering the query?"
                    )
                )
            },
        )

        return float(response.nouls["evidence"].noul)

    except Exception as exc:
        print(
            f"[Jev] evidence evaluation failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return None
