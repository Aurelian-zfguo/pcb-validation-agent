"""LLM调用客户端：统一OpenAI兼容接口，DeepSeek/Claude/harness均可对接。"""
import json
import time
from abc import ABC, abstractmethod

import requests


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list) -> str:
        """输入messages列表，返回模型回复文本。"""


class MockLLMClient(LLMClient):
    """无API密钥/未配置harness时使用：返回固定格式归因，用于跑通全链路。"""

    def chat(self, messages: list) -> str:
        items = [{
            "category": "违规行为",
            "explanation": "（模拟归因）接入真实API或DeepSeek-Harness后生成完整分析。",
            "suggestion": "通报工厂核实并纠正。",
        }] * 50
        return json.dumps({"results": items}, ensure_ascii=False)


class OpenAICompatClient(LLMClient):
    """OpenAI兼容接口：DeepSeek(deepseek-chat)、Claude(经兼容网关)均可用。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: int = 60, max_retries: int = 2, retry_backoff: int = 2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def chat(self, messages: list) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},  # 强制JSON对象输出
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except requests.exceptions.RequestException as e:
                # 401/403 鉴权错误不重试；其余（429限流/5xx/网络）重试
                resp = getattr(e, "response", None)
                if resp is not None and resp.status_code in (401, 403):
                    raise
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_backoff * (attempt + 1))
