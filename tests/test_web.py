"""Web 层单测：events 双模式、webapp 状态管理、节点 emit 事件序列。"""
import json
import queue
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os

os.environ.setdefault("LLM_API_KEY", "test-key")

import events as events_mod
import webapp as webapp_mod


# ---------- events.py 双模式 ----------

def test_emit_cli_mode_prints(capsys):
    events_mod.emit({"type": "speech_start", "side": "pro", "round": 1})
    out = capsys.readouterr().out
    assert "第 1 轮 · 正方" in out


def test_emit_cli_mode_delta_inline(capsys):
    events_mod.emit({"type": "speech_delta", "side": "pro", "round": 1, "text": "你好"})
    assert capsys.readouterr().out == "你好"


def test_emit_writer_mode_no_print(capsys):
    """有 writer 时事件透传，不打印。"""
    got = []
    with patch.object(events_mod, "get_stream_writer", lambda: got.append):
        events_mod.emit({"type": "judge", "round": 1, "status": "continue",
                         "conceded_side": None, "reason": "r"})
    assert got == [{"type": "judge", "round": 1, "status": "continue",
                    "conceded_side": None, "reason": "r"}]
    assert capsys.readouterr().out == ""


def test_emit_writer_runtime_error_falls_back(capsys):
    """get_stream_writer 抛 RuntimeError（非图上下文）→ CLI 打印。"""
    def boom():
        raise RuntimeError("no context")
    with patch.object(events_mod, "get_stream_writer", boom):
        events_mod.emit({"type": "speech_start", "side": "con", "round": 2})
    assert "第 2 轮 · 反方" in capsys.readouterr().out


# ---------- webapp.py 状态管理 ----------

def test_start_debate_empty_topic_400():
    from fastapi.testclient import TestClient
    client = TestClient(webapp_mod.app)
    r = client.post("/api/debate", json={"topic": "  "})
    assert r.status_code == 400


def test_start_debate_409_when_running():
    from fastapi.testclient import TestClient
    client = TestClient(webapp_mod.app)
    webapp_mod._debates.clear()
    with patch.object(webapp_mod, "_run_debate", lambda *a: None), \
         patch.object(webapp_mod, "threading") as t:
        r1 = client.post("/api/debate", json={"topic": "辩题"})
        assert r1.status_code == 200
        r2 = client.post("/api/debate", json={"topic": "辩题2"})
        assert r2.status_code == 409


def test_stream_unknown_id_404():
    from fastapi.testclient import TestClient
    client = TestClient(webapp_mod.app)
    webapp_mod._debates.clear()
    assert client.get("/api/stream/nope").status_code == 404


def test_stream_replays_backlog_then_sentinel():
    """重连回放：已积压事件先发，哨兵关闭。"""
    webapp_mod._debates.clear()
    q = queue.Queue()
    entry = {"queue": q, "status": "done", "events": [
        {"type": "split_done", "pro": "P", "con": "C"},
    ]}
    webapp_mod._debates["d1"] = entry
    q.put({"type": "judge", "round": 1, "status": "continue",
           "conceded_side": None, "reason": "ok"})
    q.put(None)

    from fastapi.testclient import TestClient
    client = TestClient(webapp_mod.app)
    body = client.get("/api/stream/d1").text
    assert "event: split_done" in body
    assert "event: judge" in body
    # SSE 格式校验
    lines = [ln for ln in body.splitlines() if ln.startswith("event: ")]
    assert lines[0] == "event: split_done"
    data_lines = [ln for ln in body.splitlines() if ln.startswith("data: ")]
    assert json.loads(data_lines[0][6:])["pro"] == "P"


def test_clear_finished_debate():
    from fastapi.testclient import TestClient
    client = TestClient(webapp_mod.app)
    webapp_mod._debates.clear()
    webapp_mod._debates["d2"] = {"queue": queue.Queue(), "status": "done", "events": []}
    assert client.delete("/api/debate/d2").json() == {"ok": True}
    assert "d2" not in webapp_mod._debates


def test_clear_running_debate_kept():
    from fastapi.testclient import TestClient
    client = TestClient(webapp_mod.app)
    webapp_mod._debates.clear()
    webapp_mod._debates["d3"] = {"queue": queue.Queue(), "status": "running", "events": []}
    client.delete("/api/debate/d3")
    assert "d3" in webapp_mod._debates
    webapp_mod._debates.clear()


# ---------- 节点 emit 事件序列（mock LLM，全链路） ----------

def test_full_graph_event_sequence():
    """图跑一遍，事件序列完整：split → speech ×2 → judge → done。"""
    import graph as g

    def fake_split(model, messages, **kw):
        return '{"pro": "P", "con": "C"}'

    def fake_judge(model, messages, **kw):
        return '{"status": "continue", "conceded_side": null, "reason": "r"}'

    # 轮满 1 轮结束：MAX_ROUNDS=1 时 judge 后轮满 → summarizer
    def fake_summary(model, messages, **kw):
        return "# 战报"

    types = []
    with patch("nodes.splitter.chat", fake_split), \
         patch("nodes.judge.chat", fake_judge), \
         patch("nodes.summarizer.chat", fake_summary), \
         patch("nodes.debater.chat_stream", lambda *a, **k: iter(["发言"])):
        graph = g.build_graph()
        for chunk in graph.stream({"topic": "t", "round": 1}, stream_mode="custom"):
            if isinstance(chunk, dict) and "type" in chunk:
                types.append(chunk["type"])

    # MAX_ROUNDS=12，裁判恒 continue → 跑满 12 轮（每轮 speech ×2 + judge）
    speech_count = types.count("speech_start")
    judge_count = types.count("judge")
    assert speech_count == 24  # 12 轮 × 正反各 1
    assert judge_count == 12
    assert types[0] == "split_done"
    assert types[-1] == "done"
    # 单轮事件顺序：start → delta → end
    first_speech = types.index("speech_start")
    assert types[first_speech : first_speech + 3] == ["speech_start", "speech_delta", "speech_end"]
