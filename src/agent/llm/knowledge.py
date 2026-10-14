"""调用 B 项目（RAG 知识库）检索接口，为归因提供知识补充。

设计原则：**A 项目的独立性优先**。B 服务是可选增强，任何调用失败（未启动、
超时、返回异常）都必须静默回退到原有硬编码 Prompt，绝不影响校验主流程。
"""

from __future__ import annotations

import time

import requests

from .rag_monitor import monitor

# B 项目检索服务地址。可被 main.py 用 settings 覆盖。
B_BASE_URL = "http://127.0.0.1:8000"
B_TIMEOUT_SECONDS = 15.0


def build_query(anomaly) -> str:
    """由异常项构造检索 query：规则名 + 描述，二者足以命中对应管控知识。"""
    parts = [str(anomaly.rule_name or "").strip(), str(anomaly.description or "").strip()]
    return " ".join(p for p in parts if p)


def retrieve_full(anomaly, base_url: str = B_BASE_URL,
                  timeout: float = B_TIMEOUT_SECONDS,
                  retry_times: int = 2,
                  retry_backoff_seconds: float = 0.5) -> tuple:
    """调用 B 的 /retrieve 接口，返回 (success, query, top_results)。

    top_results 为 [{content, source}] 列表（top_k=4），供监控记录「Top1-4 来源」。
    不抛异常：任何失败都返回 (False, query, [])。

    重试策略（对应 LangGraph 教程「瞬时错误 RetryPolicy」，但放在 HTTP 边界）：
    - 网络错误（ConnectionError）/ 超时（Timeout）/ 5xx → 指数退避重试 retry_times 次；
    - 4xx 客户端错误（404/422 等）与 200 → 不重试；
    - 其它异常（如 SSLError、JSON 解析失败）→ 不重试，直接降级。
    重试耗尽返回 (False, query, [])，仍由上层静默降级。
    """
    query = build_query(anomaly)
    if not query:
        return False, "", []
    url = f"{base_url.rstrip('/')}/retrieve"
    payload = {"query": query, "top_k": 4}

    for attempt in range(retry_times + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            resp = None  # 瞬时错误，走下方重试分支
        except Exception:
            return False, query, []  # 其它异常不重试，直接降级

        if resp is not None:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    return False, query, []
                results = data.get("results", [])
                top = [{"content": r.get("content", ""), "source": r.get("source", "")}
                       for r in results if isinstance(r, dict) and r.get("content")]
                return bool(top), query, top
            if resp.status_code < 500:
                return False, query, []  # 4xx 客户端错误：重试无意义

        # 瞬时错误（resp 为 None）或 5xx：指数退避后重试，耗尽则降级
        if attempt < retry_times:
            time.sleep(retry_backoff_seconds * (2 ** attempt))
    return False, query, []


def retrieve_knowledge(anomaly, base_url: str = B_BASE_URL,
                       timeout: float = B_TIMEOUT_SECONDS,
                       retry_times: int = 2,
                       retry_backoff_seconds: float = 0.5) -> str | None:
    """返回 Top-1 片段内容；失败返回 None（触发降级）。同时记录到 RAG 监控。"""
    success, query, top = retrieve_full(anomaly, base_url, timeout,
                                        retry_times, retry_backoff_seconds)
    monitor.log_retrieval(str(anomaly.order_id), query, success, top)
    return top[0]["content"] if success and top else None
