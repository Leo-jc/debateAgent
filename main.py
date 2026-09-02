"""辩论 agent 入口：python main.py "辩题"。"""
import sys

from config import check_api_key
from graph import build_graph
from state import MAX_ROUNDS


def main() -> None:
    # Windows 控制台 GBK → 强制 UTF-8，避免中文/emoji 乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")

    check_api_key()

    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('用法: python main.py "辩题"')
        raise SystemExit(1)

    topic = sys.argv[1].strip()
    print(f"辩题：{topic}")
    print(f"最大轮数：{MAX_ROUNDS}\n")

    graph = build_graph()
    result = graph.invoke({"topic": topic, "round": 1})

    print(f"\n{'=' * 40}")
    print(f"辩论结束：{result['end_reason']}")
    print(f"战报已保存：{result['report_path']}")


if __name__ == "__main__":
    main()
