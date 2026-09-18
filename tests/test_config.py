from src.agent.config import load_settings, load_field_mapping, resolve_api_key, PROJECT_ROOT


def test_project_root_points_to_project_dir():
    assert (PROJECT_ROOT / "config" / "settings.yaml").exists()


def test_load_settings_has_sections():
    s = load_settings()
    assert set(s) >= {"llm", "trace", "output"}
    assert "provider" in s["llm"] and "model" in s["llm"]


def test_field_mapping_has_supported_types():
    m = load_field_mapping()
    for t in ("补投日报", "余数入库日报", "余数报废日报", "综合日报"):
        assert t in m["report_types"]
        assert "订单号" in m["report_types"][t]


def test_resolve_api_key_env_first(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    assert resolve_api_key({"llm": {"api_key": "yaml-key"}}) == "env-key"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert resolve_api_key({"llm": {"api_key": "yaml-key"}}) == "yaml-key"
    assert resolve_api_key({"llm": {"api_key": ""}}) == ""


def test_knowledge_base_url_env_override(monkeypatch):
    """设置 KNOWLEDGE_BASE_URL 后，load_settings() 返回的 base_url 应是被覆盖的值。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_URL", "http://host.docker.internal:8000")
    s = load_settings()
    assert s["knowledge"]["base_url"] == "http://host.docker.internal:8000"
    monkeypatch.delenv("KNOWLEDGE_BASE_URL")
    # 未设置 env 时回落到 settings.yaml 的值
    assert load_settings()["knowledge"]["base_url"] == "http://127.0.0.1:8000"


def test_knowledge_base_url_fallback_when_missing(monkeypatch, tmp_path):
    """knowledge 字段缺失时，load_settings 不 KeyError，并落到字面量默认值。"""
    import yaml
    p = tmp_path / "settings.yaml"
    p.write_text("llm: {}\n", encoding="utf-8")
    monkeypatch.delenv("KNOWLEDGE_BASE_URL", raising=False)
    from src.agent.config import load_settings as ls
    s = ls(path=p)
    assert s["knowledge"]["base_url"] == "http://127.0.0.1:8000"
