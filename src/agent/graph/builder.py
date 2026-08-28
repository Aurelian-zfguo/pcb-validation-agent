"""图装配：把节点与条件边连成执行图。

图为无环 DAG，无 checkpointer（不做 HITL），因此不存在递归超限风险。
"""
from langgraph.graph import END, START, StateGraph

from .nodes import (attribute, attribute_skipped, enrich, guard, load_config,
                    parse_factory, parse_file, route_after_parse,
                    route_after_validate, route_mode, validate, write_report)
from .state import AgentState


def build_graph():
    b = StateGraph(AgentState)

    b.add_node("load_config", load_config)
    b.add_node("parse_file", parse_file)
    b.add_node("parse_factory", parse_factory)
    b.add_node("enrich", enrich)
    b.add_node("validate", validate)
    b.add_node("attribute", attribute)
    b.add_node("attribute_skipped", attribute_skipped)
    b.add_node("write_report", write_report)

    b.add_edge(START, "load_config")
    # 双模式加载分支（配置失败则短路）
    b.add_conditional_edges("load_config", route_mode,
                            ["parse_file", "parse_factory", END])
    # 解析失败短路
    b.add_conditional_edges("parse_file", route_after_parse, ["enrich", END])
    b.add_conditional_edges("parse_factory", route_after_parse, ["enrich", END])
    b.add_conditional_edges("enrich", guard("validate"), ["validate", END])
    # 数据驱动分支 + 降级分支
    b.add_conditional_edges("validate", route_after_validate,
                            ["attribute", "attribute_skipped", END])
    # attribute / attribute_skipped 都是 degrade，不会写 error，直连即可
    b.add_edge("attribute", "write_report")
    b.add_edge("attribute_skipped", "write_report")
    b.add_edge("write_report", END)

    return b.compile()
