"""LLM 提供商配置"""

import os
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=False)


class LMStudioConfig:
    """LM Studio 配置类"""

    HOST = os.getenv("LM_STUDIO_HOST", "127.0.0.1")
    PORT = int(os.getenv("LM_STUDIO_PORT", "4060"))
    MODEL = os.getenv("LM_STUDIO_MODEL", "qwopus3.5-9b-v3")
    CONTEXT_LENGTH = int(os.getenv("LM_STUDIO_CONTEXT_LENGTH", "65536"))

    @classmethod
    def get_base_url(cls) -> str:
        return f"http://{cls.HOST}:{cls.PORT}"

    @classmethod
    def get_chat_url(cls) -> str:
        return f"{cls.get_base_url()}/api/v1/chat"


class DeepSeekConfig:
    """DeepSeek API 配置类（v4-flash + thinking 支持）"""

    API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "max")
    THINKING_ENABLED = os.getenv("DEEPSEEK_THINKING_ENABLED", "true").lower() == "true"

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.API_KEY)

    @classmethod
    def get_headers(cls) -> dict:
        return {
            "Authorization": f"Bearer {cls.API_KEY}",
            "Content-Type": "application/json"
        }
