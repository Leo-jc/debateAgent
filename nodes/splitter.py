"""主 agent 拆题节点：原始辩题 → 正反两个对立命题。"""
import sys

from llm import chat, parse_json
from config import MODEL_SPLIT
from events import emit
from state import DebateState

MAX_SPLIT_RETRIES = 2  # JSON 解析失败重试次数；仍失败则退出（唯一无降级的步骤）

_SPLIT_PROMPT = """你是辩论赛出题人。用户给出一个辩题，你把它拆成两个对立命题。

要求：
1. "pro" 是正方命题，"con" 是反方命题，两者必须是同一辩题的对立两面。
2. 每个命题为一句话，立场清晰、可直接辩护。
3. 只输出 JSON，格式：{{"pro": "...", "con": "..."}}，不要输出其他内容。

辩题：{topic}"""


def split_topic(state: DebateState) -> dict:
    """拆题节点：一次 LLM 调用产出正反命题。解析失败重试后仍失败则退出。"""
    topic = state["topic"]
    messages = [{"role": "user", "content": _SPLIT_PROMPT.format(topic=topic)}]

    last_err: Exception | None = None
    for attempt in range(MAX_SPLIT_RETRIES + 1):
        try:
            raw = chat(MODEL_SPLIT, messages, json_mode=True)
            result = parse_json(raw)
            pro, con = result["pro"].strip(), result["con"].strip()
            if pro and con:
                emit({"type": "split_done", "pro": pro, "con": con})
                return {"pro_position": pro, "con_position": con}
            last_err = ValueError(f"命题为空: {result}")
        except Exception as err:  # noqa: BLE001 JSON 缺字段/解析失败
            last_err = err

    print(
        f"\n拆题失败（已重试 {MAX_SPLIT_RETRIES} 次）：{last_err}\n请重新运行并换一种表述输入辩题。",
        file=sys.stderr,
    )
    raise SystemExit(2)
