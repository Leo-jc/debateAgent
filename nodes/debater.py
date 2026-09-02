"""正/反方共用发言节点工厂。流式发言经 emit() 输出（CLI 打印 / Web SSE），文本进入 transcripts。"""
from collections.abc import Callable

from llm import chat_stream
from config import MODEL_CON, MODEL_PRO
from events import emit
from state import DebateState, MAX_SPEECH_CHARS

_SPEECH_PROMPT = """你是辩论赛的{side_name}辩手。你的立场是：{position}

规则：
1. 每次发言聚焦 1-2 个核心论点展开论证。
2. {respond_rule}
3. 不得修改己方立场，不许出现任何放弃性表述（如认输、称赞对方立场正确）。
4. 只输出辩论正文，300-500 字，不要元信息、不要标题。"""

_FIRST_RESPOND = "这是第一轮发言，直接立论。"
_RESPOND = "必须直接回应对方上一轮的反驳，先回应再立论。"


def _format_history(state: DebateState) -> str:
    """把已有发言整理成对话记录文本。"""
    if not state["transcripts"]:
        return ""
    lines = ["以下是此前的辩论记录："]
    for t in state["transcripts"]:
        side = "正方" if t["side"] == "pro" else "反方"
        lines.append(f"【{side} · 第 {t['round']} 轮】{t['text']}")
    return "\n".join(lines)


def make_debater(
    side: str, model: str
) -> Callable[[DebateState], dict]:
    """生成一个辩手节点函数。side: "pro" 或 "con"。"""

    def debater(state: DebateState) -> dict:
        side_name = "正方" if side == "pro" else "反方"
        position = state["pro_position"] if side == "pro" else state["con_position"]
        opponent = "con" if side == "pro" else "pro"
        is_first = not any(t["side"] == opponent for t in state["transcripts"])

        messages = [
            {
                "role": "system",
                "content": _SPEECH_PROMPT.format(
                    side_name=side_name,
                    position=position,
                    topic=state["topic"],
                    respond_rule=_FIRST_RESPOND if is_first else _RESPOND,
                ),
            },
            {
                "role": "user",
                "content": (_format_history(state) + "\n\n" if state["transcripts"] else "")
                + f"辩题：{state['topic']}\n请发表你这一轮的辩论发言。",
            },
        ]

        # 流式输出：角色标头 + 打字机效果
        emit({"type": "speech_start", "side": side, "round": state["round"]})
        parts: list[str] = []
        try:
            for chunk in chat_stream(model, messages):
                parts.append(chunk)
                emit({"type": "speech_delta", "side": side, "round": state["round"], "text": chunk})
            emit({"type": "speech_end", "side": side, "round": state["round"]})
        except Exception as err:  # noqa: BLE001 重试耗尽仍失败
            emit({"type": "speech_end", "side": side, "round": state["round"]})
            emit({"type": "error", "message": f"发言失败，此轮弃权（{type(err).__name__}: {err}）"})

        text = "".join(parts)[:MAX_SPEECH_CHARS] or "[发言失败，此轮弃权]"
        return {"transcripts": [{"side": side, "round": state["round"], "text": text}]}

    return debater


pro_debater = make_debater("pro", MODEL_PRO)
con_debater = make_debater("con", MODEL_CON)
