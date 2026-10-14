"""pytest 全局配置：加速含网络/重试的测试。

- 重试退避用 ``time.sleep`` 实现，测试里打桩成 no-op（重试逻辑照跑、只省退避延迟）。
- ``requests.post`` 打桩成立即抛 ``ConnectionError``：本项目 HTTP 只用于「调 B 知识库」，
  是可选增强、失败即降级，测试没必要真连 127.0.0.1（Windows 上连接被拒一次约 2s）。
  需要自定义响应/真发请求的用例，在用例内用自己的 monkeypatch 覆盖即可。
"""
import pytest
import requests


@pytest.fixture(autouse=True)
def _disable_retry_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)


@pytest.fixture(autouse=True)
def _stub_http_post(monkeypatch):
    def _raise(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused (stubbed in tests)")

    monkeypatch.setattr(requests, "post", _raise)
