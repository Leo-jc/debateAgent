"""共享状态定义与常量。"""
from typing import Annotated, Any, TypedDict

MAX_ROUNDS = 12           # 最大辩论轮数（一轮 = 正方 + 反方 + 裁判）
MAX_SPEECH_CHARS = 800    # 发言截断兜底长度


def merge_transcripts(
    current: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """transcripts 追加式合并。"""
    return current + new


def merge_judge_records(
    current: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """judge_records 追加式合并。"""
    return current + new


class DebateState(TypedDict):
    topic: str                 # 原始辩题
    pro_position: str          # 拆出的正方命题
    con_position: str          # 拆出的反方命题
    transcripts: Annotated[list[dict[str, Any]], merge_transcripts]
    # 每条 {"side": "pro"|"con", "round": n, "text": str}
    round: int                 # 当前轮数
    judge_records: Annotated[list[dict[str, Any]], merge_judge_records]
    # 每条 {"round", "status", "conceded_side", "reason"}
    end_reason: str            # 最终结束原因
    report_path: str           # 战报文件路径
