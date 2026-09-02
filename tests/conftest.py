import os
import sys
from pathlib import Path

# 让 tests 能 import 项目根目录的模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 单测不依赖真实 key
os.environ.setdefault("LLM_API_KEY", "test-key")
