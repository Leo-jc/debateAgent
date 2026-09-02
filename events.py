"""事件发射抽象：CLI 打印 / LangGraph 自定义流 双模式。

节点内不再直接 print，统一调 emit()：
- CLI（graph.invoke）：按事件类型打印到终端，行为与改造前一致
- Web（graph.stream(stream_mode="custom")）：事件经 get_stream_writer()
  透传给消费方（webapp.py），再由 SSE 推给浏览器
"""
import sys

try:
    from langgraph.config import get_stream_writer
except ImportError:  # 老版本 langgraph 无此 API
    get_stream_writer = None


def _print_event(event: dict) -> None:
    """CLI 模式的事件打印（与改造前的终端输出保持一致）。"""
    etype = event.get("type")
    if etype == "speech_start":
        print(f"\n【第 {event['round']} 轮 · {'正方' if event['side'] == 'pro' else '反方'}】")
    elif etype == "speech_delta":
        print(event["text"], end="", flush=True)
    elif etype == "speech_end":
        print()
    elif etype == "judge":
        conceded = event.get("conceded_side")
        line = f"\n[裁判] {event['status']}"
        if conceded:
            line += f"（{'正方' if conceded == 'pro' else '反方'}认输）"
        print(line + f"：{event['reason']}")
    elif etype == "split_done":
        print(f"正方命题：{event['pro']}\n反方命题：{event['con']}\n")
    elif etype == "done":
        pass  # done 由 main.py 统一打印，避免重复
    elif etype == "error":
        print(f"\n[错误] {event['message']}", file=sys.stderr)


def emit(event: dict) -> None:
    """双模式事件发射：图流式上下文里透传给 writer，否则 CLI 打印。"""
    writer = None
    if get_stream_writer is not None:
        try:
            writer = get_stream_writer()
        except RuntimeError:  # 不在 runnable 上下文（CLI / 单测）
            writer = None
    if callable(writer):
        writer(event)
    else:
        _print_event(event)
