"""全局配置：模型角色分配 + 网关接入。

单一火山网关（OpenAI 兼容），一个 api-key 覆盖全部角色。
"""
import os

from dotenv import load_dotenv

load_dotenv()

LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "https://st8tp3ajl0df3n8b8l8qu.apigateway-cn-beijing.volceapi.com/v1",
)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# 各角色的模型分配
MODEL_PRO = "deepseek-v4-pro"        # 正方辩手
MODEL_CON = "glm-5.3-flash"          # 反方辩手
MODEL_SPLIT = "glm-5.3-flash"        # 主 agent 拆题
MODEL_JUDGE = "glm-5.3-flash"        # 裁判
MODEL_SUMMARY = "deepseek-v4-pro"    # 主 agent 总结


def check_api_key() -> None:
    """启动时检查 key，缺失则报错退出。"""
    if not LLM_API_KEY:
        raise SystemExit(
            "缺少 API key：请在项目根目录 .env 中设置 LLM_API_KEY"
        )
