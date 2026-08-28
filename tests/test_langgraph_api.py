"""锁定本项目依赖的 LangGraph API 契约。

这是少见的"测第三方库"的测试，理由：整个 graph/ 包建立在下面三条假设上，
一旦 langgraph 升级破坏了它们，这里失败比在 8 个节点里排查便宜得多。
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class _S(TypedDict, total=False):
    n: int
    path: str


def _build():
    def start(state):
        return {"n": state.get("n", 0) + 1}

    def left(state):
        return {"path": "left"}

    def right(state):
        return {"path": "right"}

    def route(state):
        return "left" if state["n"] > 0 else "right"

    b = StateGraph(_S)
    b.add_node("start", start)
    b.add_node("left", left)
    b.add_node("right", right)
    b.add_edge(START, "start")
    b.add_conditional_edges("start", route, ["left", "right"])
    b.add_edge("left", END)
    b.add_edge("right", END)
    return b.compile()


def test_conditional_edges_route_by_return_value():
    """假设1：路由函数返回节点名字符串即可决定走向。"""
    assert _build().invoke({"n": 5})["path"] == "left"
    assert _build().invoke({"n": -5})["path"] == "right"


def test_stream_multi_mode_yields_mode_chunk_tuples():
    """假设2：stream_mode=["updates","values"] 产出 (mode, chunk) 二元组。

    updates 的 chunk 形如 {节点名: 局部更新}；values 的 chunk 是完整 State 快照。
    main.py 靠这个形态同时拿到"节点进度"和"最终状态"。
    """
    modes, updates_nodes, last_values = [], [], None
    for mode, chunk in _build().stream({"n": 5}, stream_mode=["updates", "values"]):
        modes.append(mode)
        if mode == "updates":
            updates_nodes.extend(chunk.keys())
        else:
            last_values = chunk

    assert set(modes) <= {"updates", "values"}
    assert "start" in updates_nodes and "left" in updates_nodes
    assert last_values is not None and last_values["path"] == "left"


def test_conditional_edges_can_target_end():
    """假设3：路由函数可以返回 END 直接终止，用于错误短路。"""
    def only(state):
        return {"path": "done"}

    b = StateGraph(_S)
    b.add_node("only", only)
    b.add_edge(START, "only")
    b.add_conditional_edges("only", lambda s: END, [END])
    assert b.compile().invoke({"n": 1})["path"] == "done"
