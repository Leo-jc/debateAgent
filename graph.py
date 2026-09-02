"""StateGraph 组装：splitter → (pro → con → judge) 循环 → summarizer。"""
from langgraph.graph import StateGraph, START, END

from state import DebateState, MAX_ROUNDS
from nodes.splitter import split_topic
from nodes.debater import pro_debater, con_debater
from nodes.judge import judge
from nodes.summarizer import summarize


def _pro_with_round(state: DebateState) -> dict:
    """pro 节点包装：有过发言则轮数 +1（条件边不能改状态）。"""
    if state["transcripts"]:
        return {**pro_debater(state), "round": state["round"] + 1}
    return pro_debater(state)


def _summarizer_with_reason(state: DebateState) -> dict:
    """summarizer 包装：进入前计算 end_reason（条件边不能改状态）。"""
    last = state["judge_records"][-1] if state["judge_records"] else {}
    if last.get("status") == "concede":
        loser = "正方" if last["conceded_side"] == "pro" else "反方"
        end_reason = f"第 {state['round']} 轮后{loser}认输：{last['reason']}"
    else:
        end_reason = f"达到最大轮数 {MAX_ROUNDS}，辩论正常结束"
    result = summarize(state)
    return {**result, "end_reason": end_reason}


def _after_judge(state: DebateState) -> str:
    """条件边只做路由；end_reason 和轮数推进分别在 summarizer 前置信息与 pro 节点里完成。"""
    last = state["judge_records"][-1] if state["judge_records"] else {}
    if last.get("status") == "concede" or state["round"] >= MAX_ROUNDS:
        return "summarizer"
    return "pro"


def build_graph():
    g = StateGraph(DebateState)
    g.add_node("splitter", split_topic)
    g.add_node("pro", _pro_with_round)
    g.add_node("con", con_debater)
    g.add_node("judge", judge)
    g.add_node("summarizer", _summarizer_with_reason)

    g.add_edge(START, "splitter")
    g.add_edge("splitter", "pro")
    g.add_edge("pro", "con")
    g.add_edge("con", "judge")
    g.add_conditional_edges("judge", _after_judge, {"pro": "pro", "summarizer": "summarizer"})
    g.add_edge("summarizer", END)
    return g.compile()
