"""FastAPI Web 应用：发起辩论 + SSE 直播。

架构：POST /api/debate 起 daemon 线程跑 graph.stream(stream_mode="custom")，
自定义事件写入内存队列；GET /api/stream/{id} 用 StreamingResponse 消费队列推 SSE。
同时只允许一个辩论运行（避免 API 限流），重复请求 409。
"""
import json
import queue
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import check_api_key

app = FastAPI(title="DebateAgent")

_STATIC_DIR = Path(__file__).resolve().parent / "static"

# 辩论生命周期：id -> {"queue": Queue, "status": "running"|"done"|"error", "events": [已发事件]}
_debates: dict[str, dict] = {}
_lock = threading.Lock()


class TopicIn(BaseModel):
    topic: str


def _run_debate(debate_id: str, topic: str) -> None:
    """后台线程：跑图，把 custom 事件灌进队列。"""
    from graph import build_graph

    entry = _debates[debate_id]
    q: queue.Queue = entry["queue"]
    try:
        graph = build_graph()
        for chunk in graph.stream({"topic": topic, "round": 1}, stream_mode="custom"):
            if isinstance(chunk, dict) and "type" in chunk:
                q.put(chunk)
                with _lock:
                    entry["events"].append(chunk)
        entry["status"] = "done"
    except Exception as err:  # noqa: BLE001 线程内兜底，错误推给前端
        q.put({"type": "error", "message": f"{type(err).__name__}: {err}"})
        entry["status"] = "error"
    finally:
        q.put(None)  # 结束哨兵


@app.post("/api/debate")
def start_debate(body: TopicIn):
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="辩题不能为空")

    with _lock:
        running = next((d for d in _debates.values() if d["status"] == "running"), None)
        if running:
            raise HTTPException(status_code=409, detail="已有辩论进行中，请等待完成")

        check_api_key()
        debate_id = uuid.uuid4().hex[:12]
        _debates[debate_id] = {"queue": queue.Queue(), "status": "running", "events": []}

    threading.Thread(target=_run_debate, args=(debate_id, topic), daemon=True).start()
    return {"debate_id": debate_id}


@app.get("/api/stream/{debate_id}")
def stream_debate(debate_id: str):
    if debate_id not in _debates:
        raise HTTPException(status_code=404, detail="辩论不存在")

    def gen():
        # 回放已积压事件（页面刷新重连续传），再实时跟随队列
        with _lock:
            entry = _debates[debate_id]
            replayed = list(entry["events"])
        for ev in replayed:
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        q: queue.Queue = entry["queue"]
        while True:
            ev = q.get()
            if ev is None:  # 结束哨兵
                break
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/debate/{debate_id}")
def clear_debate(debate_id: str):
    """辩论结束后清掉，允许发起下一场。"""
    with _lock:
        entry = _debates.get(debate_id)
        if entry and entry["status"] != "running":
            del _debates[debate_id]
    return {"ok": True}


app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
