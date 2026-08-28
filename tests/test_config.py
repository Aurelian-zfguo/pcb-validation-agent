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
