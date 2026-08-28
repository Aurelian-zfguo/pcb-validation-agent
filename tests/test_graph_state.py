from src.agent.graph.state import AgentState


def test_state_is_total_false_typeddict():
    """total=False：节点只返回局部更新，不必填满所有字段。"""
    assert AgentState.__total__ is False


def test_state_declares_all_pipeline_fields():
    keys = set(AgentState.__annotations__)
    expected = {
        # 输入
        "factory", "report_type", "file_path", "sheet",
        "bt_files", "order_files", "hist_files",
        "output_dir", "trace_dir", "use_mock",
        # 运行时句柄
        "settings", "field_mapping", "tracer", "engine", "llm_client",
        # 中间数据
        "report", "order_df", "hist_index", "anomalies", "rule_errors",
        # 输出
        "attributions", "skip_reason", "excel_path", "md_path",
        # 控制流
        "messages", "error", "exit_code",
    }
    assert keys == expected


def test_messages_uses_add_reducer():
    """messages 是唯一带 reducer 的字段：多个节点的警告要累加而非覆盖。"""
    import operator
    from typing import get_args
    ann = AgentState.__annotations__["messages"]
    assert operator.add in get_args(ann)
