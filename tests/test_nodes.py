"""mock LLM 测试：拆分、裁判三分支、条件边走向、截断逻辑。"""
from unittest.mock import patch

import pytest

import nodes.splitter as splitter_mod
import nodes.judge as judge_mod
from graph import _after_judge, build_graph
from state import MAX_ROUNDS, DebateState
from nodes.debater import make_debater
from nodes.summarizer import _safe_filename


# ---------- 拆分节点 ----------

def test_split_topic_success():
    with patch.object(splitter_mod, "chat", return_value='{"pro": "躺平合理", "con": "躺平不合理"}'):
        result = splitter_mod.split_topic({"topic": "该不该躺平"})
    assert result == {"pro_position": "躺平合理", "con_position": "躺平不合理"}


def test_split_topic_json_fence_tolerated():
    with patch.object(splitter_mod, "chat", return_value='```json\n{"pro": "A", "con": "B"}\n```'):
        result = splitter_mod.split_topic({"topic": "辩题"})
    assert result["pro_position"] == "A"


def test_split_topic_retries_then_exit():
    calls = []
    with patch.object(splitter_mod, "chat", side_effect=lambda *a, **k: calls.append(1) or "not json"):
        with pytest.raises(SystemExit):
            splitter_mod.split_topic({"topic": "辩题"})
    assert len(calls) == splitter_mod.MAX_SPLIT_RETRIES + 1


# ---------- 裁判节点三分支 ----------

def _judge_state(round_=1, transcripts=None):
    return {
        "topic": "辩题", "pro_position": "P", "con_position": "C",
        "round": round_, "transcripts": transcripts or [],
        "judge_records": [], "end_reason": "", "report_path": "",
    }


def test_judge_continue():
    with patch.object(judge_mod, "chat", return_value='{"status": "continue", "conceded_side": null, "reason": "尚在攻防"}'):
        result = judge_mod.judge(_judge_state())
    assert result["judge_records"][0]["status"] == "continue"


def test_judge_concede_pro():
    with patch.object(judge_mod, "chat", return_value='{"status": "concede", "conceded_side": "pro", "reason": "正方矛盾"}'):
        result = judge_mod.judge(_judge_state())
    rec = result["judge_records"][0]
    assert rec["status"] == "concede" and rec["conceded_side"] == "pro"


def test_judge_concede_con():
    with patch.object(judge_mod, "chat", return_value='{"status": "concede", "conceded_side": "con", "reason": "反方无法回应"}'):
        result = judge_mod.judge(_judge_state())
    rec = result["judge_records"][0]
    assert rec["conceded_side"] == "con"


def test_judge_bad_json_defaults_continue():
    with patch.object(judge_mod, "chat", return_value="完全不是 JSON"):
        result = judge_mod.judge(_judge_state())
    rec = result["judge_records"][0]
    assert rec["status"] == "continue" and rec["conceded_side"] is None


def test_judge_concede_without_side_defaults_continue():
    with patch.object(judge_mod, "chat", return_value='{"status": "concede", "conceded_side": null, "reason": "x"}'):
        result = judge_mod.judge(_judge_state())
    assert result["judge_records"][0]["status"] == "continue"


# ---------- 条件边走向 ----------

def test_after_judge_routes_to_summarizer_on_concede():
    state = {"round": 3, "judge_records": [{"status": "concede", "conceded_side": "con", "reason": "r"}], "end_reason": ""}
    assert _after_judge(state) == "summarizer"


def test_after_judge_routes_to_summarizer_on_max_rounds():
    state = {"round": MAX_ROUNDS, "judge_records": [{"status": "continue", "conceded_side": None, "reason": ""}], "end_reason": ""}
    assert _after_judge(state) == "summarizer"


def test_after_judge_loops_on_continue():
    state = {"round": 2, "judge_records": [{"status": "continue", "conceded_side": None, "reason": ""}], "end_reason": ""}
    assert _after_judge(state) == "pro"


def test_summarizer_wrapper_sets_end_reason():
    from graph import _summarizer_with_reason
    state = {"topic": "t", "pro_position": "P", "con_position": "C", "round": 3,
             "transcripts": [], "judge_records": [{"status": "concede", "conceded_side": "con", "reason": "r"}],
             "end_reason": "", "report_path": ""}
    with patch("graph.summarize", return_value={"report_path": "x"}):
        result = _summarizer_with_reason(state)
    assert result["end_reason"] == "第 3 轮后反方认输：r"
    assert result["report_path"] == "x"


def test_graph_compiles():
    assert build_graph() is not None


# ---------- 发言节点：截断 + 失败降级 ----------

def test_debater_truncates_long_speech():
    def fake_stream(model, messages, **kw):
        yield "好" * 2000

    with patch("nodes.debater.chat_stream", fake_stream):
        node = make_debater("pro", "test-model")
        result = node({"topic": "t", "pro_position": "P", "con_position": "C", "round": 1, "transcripts": [], "judge_records": [], "end_reason": "", "report_path": ""})
    assert len(result["transcripts"][0]["text"]) == 800


def test_debater_failure_fallback(capsys):
    def bad_stream(model, messages, **kw):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    with patch("nodes.debater.chat_stream", bad_stream):
        node = make_debater("con", "test-model")
        result = node({"topic": "t", "pro_position": "P", "con_position": "C", "round": 1, "transcripts": [], "judge_records": [], "end_reason": "", "report_path": ""})
    assert result["transcripts"][0]["text"] == "[发言失败，此轮弃权]"


def test_debater_respond_rule_switches():
    captured = {}

    def fake_stream(model, messages, **kw):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        yield "x"

    base = {"topic": "t", "pro_position": "P", "con_position": "C", "round": 1, "judge_records": [], "end_reason": "", "report_path": ""}
    node = make_debater("con", "test-model")
    with patch("nodes.debater.chat_stream", fake_stream):
        # 第一轮（无正方发言）→ 立论
        node({**base, "transcripts": []})
        assert "直接立论" in captured["system"]
        # 有正方发言 → 必须回应
        node({**base, "transcripts": [{"side": "pro", "round": 1, "text": "hello"}]})
        assert "回应对方上一轮" in captured["system"]
        assert "hello" in captured["user"]  # 历史在 user 消息里


def test_debater_always_has_user_message():
    """网关拒绝只有 system 的请求，必须始终有 user 消息。"""
    captured = {}

    def fake_stream(model, messages, **kw):
        captured["roles"] = [m["role"] for m in messages]
        yield "x"

    base = {"topic": "t", "pro_position": "P", "con_position": "C", "round": 1, "judge_records": [], "end_reason": "", "report_path": ""}
    node = make_debater("con", "test-model")
    with patch("nodes.debater.chat_stream", fake_stream):
        node({**base, "transcripts": []})
    assert captured["roles"] == ["system", "user"]


# ---------- 文件名清洗 ----------

def test_safe_filename():
    assert _safe_filename('人类应不应该/追求"长生不老"？') == "人类应不应该-追求-长生不老-？"


def test_safe_filename_empty():
    assert _safe_filename("///") == "debate"
