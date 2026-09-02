"""主 agent 总结节点：生成完整战报 Markdown 写入 output/。"""
import re
from datetime import datetime
from pathlib import Path

from llm import chat
from config import MODEL_SUMMARY
from events import emit
from state import DebateState

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

_SUMMARY_PROMPT = """你是辩论赛主裁判兼战报记者。根据以下材料撰写一份完整战报 Markdown。

材料：
- 辩题：{topic}
- 正方命题：{pro}
- 反方命题：{con}
- 结束原因：{end_reason}
- 裁判记录：{judges}
- 辩论全文：
{history}

战报固定结构（用 Markdown 二级标题分节）：
## 辩题信息（辩题、双方命题、结束原因）
## 双方立场概述
## 每轮核心交锋点（逐轮概括双方攻防要点）
## 双方核心论点与漏洞（分正方/反方两小节）
## 最终胜方与理由

胜方推导规则：{winner_rule}
只输出 Markdown 正文。"""


def _format_history(state: DebateState) -> str:
    lines = []
    for t in state["transcripts"]:
        side = "正方" if t["side"] == "pro" else "反方"
        lines.append(f"【{side} · 第 {t['round']} 轮】{t['text']}")
    return "\n".join(lines)


def _winner_rule(state: DebateState) -> str:
    conceded = next(
        (r for r in state["judge_records"] if r["status"] == "concede"), None
    )
    if conceded:
        loser = "正方" if conceded["conceded_side"] == "pro" else "反方"
        return f"{loser}被判定认输，对方获胜。认输理由：{conceded['reason']}"
    return "达到最大轮数结束。请依据双方整体表现判定胜方，并明确说明理由。"


def _safe_filename(topic: str) -> str:
    """辩题转文件名：去掉非法字符，限长 40。"""
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "-", topic.strip())
    return (cleaned[:40].rstrip("-") or "debate")


def summarize(state: DebateState) -> dict:
    """总结节点：deepseek 生成战报，写入 output/日期-辩题.md。"""
    prompt = _SUMMARY_PROMPT.format(
        topic=state["topic"],
        pro=state["pro_position"],
        con=state["con_position"],
        end_reason=state.get("end_reason", ""),
        judges="\n".join(
            f"第{r['round']}轮: {r['status']}" + (f" {r['conceded_side']}认输" if r.get("conceded_side") else "") + f"（{r['reason']}）"
            for r in state["judge_records"]
        ),
        history=_format_history(state),
        winner_rule=_winner_rule(state),
    )
    report = chat(MODEL_SUMMARY, [{"role": "user", "content": prompt}])

    _OUTPUT_DIR.mkdir(exist_ok=True)
    path = _OUTPUT_DIR / f"{datetime.now():%Y-%m-%d}-{_safe_filename(state['topic'])}.md"
    path.write_text(report, encoding="utf-8")
    emit({"type": "done", "report_path": str(path), "report": report})
    return {"report_path": str(path)}
