"""裁判节点：每轮结束后判定继续 / 认输。"""
from llm import chat, parse_json
from config import MODEL_JUDGE
from events import emit
from state import DebateState

_JUDGE_PROMPT = """你是辩论赛裁判。根据辩题和双方全部发言，判断辩论是否应该结束。

判定标准：
1. 仅当一方的核心论点已被对方系统性质疑且无法自洽回应，或出现明确自相矛盾时，判该方认输（concede）。
2. 正常攻防往来一律判 continue。
3. 严禁为了省事提前终止辩论。

只输出 JSON：{{"status": "continue" 或 "concede", "conceded_side": "pro" 或 "con" 或 null, "reason": "一句话"}}

辩题：{topic}
正方命题：{pro}
反方命题：{con}

{history}"""


def _format_history(state: DebateState) -> str:
    lines = []
    for t in state["transcripts"]:
        side = "正方" if t["side"] == "pro" else "反方"
        lines.append(f"【{side} · 第 {t['round']} 轮】{t['text']}")
    return "\n".join(lines)


def judge(state: DebateState) -> dict:
    """裁判节点。JSON 解析失败重试 1 次后视为 continue（宁可多辩不误停）。"""
    prompt = _JUDGE_PROMPT.format(
        topic=state["topic"],
        pro=state["pro_position"],
        con=state["con_position"],
        history=_format_history(state),
    )
    messages = [{"role": "user", "content": prompt}]

    verdict: dict | None = None
    for _ in range(2):  # 首次 + 重试 1 次
        try:
            verdict = parse_json(chat(MODEL_JUDGE, messages, json_mode=True))
            break
        except Exception:  # noqa: BLE001
            verdict = None

    if verdict is None or verdict.get("status") not in ("continue", "concede"):
        status, conceded, reason = "continue", None, "裁判判定异常，默认继续"
    else:
        status = verdict["status"]
        conceded = verdict.get("conceded_side")
        reason = verdict.get("reason", "")
        if status == "concede" and conceded not in ("pro", "con"):
            status, conceded = "continue", None  # concede 但缺认输方 → 视为异常

    emit(
        {
            "type": "judge",
            "round": state["round"],
            "status": status,
            "conceded_side": conceded,
            "reason": reason,
        }
    )
    return {
        "judge_records": [
            {
                "round": state["round"],
                "status": status,
                "conceded_side": conceded,
                "reason": reason,
            }
        ]
    }
