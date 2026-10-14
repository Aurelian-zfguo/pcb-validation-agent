"""B 项目知识检索联动测试：retrieve_knowledge 与 build_prompt 的知识注入。"""

from __future__ import annotations

import requests
from types import SimpleNamespace

from src.agent.llm.attribution import build_prompt
from src.agent.llm.knowledge import build_query, retrieve_knowledge
from src.agent.schema import Anomaly


def _make_anomaly():
    return Anomaly(rule_id="R2", rule_name="补投超标", factory="珠海一厂",
                   order_id="X1", description="预大率超标", evidence={})


def test_build_query_combines_rule_name_and_description():
    q = build_query(_make_anomaly())
    assert q == "补投超标 预大率超标"


def test_retrieve_knowledge_degrades_when_service_down():
    # 端口 9999 无服务，应返回 None 而非抛异常
    assert retrieve_knowledge(_make_anomaly(), base_url="http://127.0.0.1:9999",
                              timeout=0.5) is None


def test_build_prompt_injects_knowledge_when_retriever_provided():
    def fake_retriever(anomaly):
        return "【知识】偏离投料标准±5%需审批。"

    prompt = build_prompt([_make_anomaly()], retriever=fake_retriever)
    assert "【知识补充】" in prompt
    assert "偏离投料标准±5%需审批" in prompt


def test_build_prompt_degrades_silently_when_retriever_raises():
    def broken_retriever(anomaly):
        raise RuntimeError("服务挂了")

    prompt = build_prompt([_make_anomaly()], retriever=broken_retriever)
    assert "【知识补充】" not in prompt
    assert "R2" in prompt  # 原有硬编码内容仍在


def test_build_prompt_without_retriever_unchanged():
    # 默认 retriever=None 时行为与改造前一致
    prompt = build_prompt([_make_anomaly()])
    assert "【知识补充】" not in prompt
    assert "R2" in prompt


# ─────────────────────────── 瞬时错误重试 ───────────────────────────

def test_retry_then_success(monkeypatch):
    """前两次连接失败、第三次成功：应重试到成功并返回内容。"""
    attempts = {"n": 0}
    good = SimpleNamespace(status_code=200,
                           json=lambda: {"results": [{"content": "制度条文", "source": "a.md"}]})

    def fake_post(*a, **k):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise requests.exceptions.ConnectionError("connection refused")
        return good

    monkeypatch.setattr("requests.post", fake_post)

    got = retrieve_knowledge(_make_anomaly(), base_url="http://x",
                             retry_times=2, retry_backoff_seconds=0)
    assert got == "制度条文"
    assert attempts["n"] == 3


def test_retry_exhausted(monkeypatch):
    """连续连接失败耗尽重试：返回 None，由上层静默降级。"""
    def fake_post(*a, **k):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("requests.post", fake_post)

    got = retrieve_knowledge(_make_anomaly(), base_url="http://x",
                             retry_times=2, retry_backoff_seconds=0)
    assert got is None


def test_4xx_no_retry(monkeypatch):
    """4xx 客户端错误：不重试，直接返回 None。"""
    attempts = {"n": 0}
    not_found = SimpleNamespace(status_code=404)

    def fake_post(*a, **k):
        attempts["n"] += 1
        return not_found

    monkeypatch.setattr("requests.post", fake_post)

    got = retrieve_knowledge(_make_anomaly(), base_url="http://x",
                             retry_times=2, retry_backoff_seconds=0)
    assert got is None
    assert attempts["n"] == 1  # 4xx 不重试
