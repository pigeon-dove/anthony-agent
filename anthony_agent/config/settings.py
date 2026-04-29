"""Anthony Agent - 全局配置"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# 用户级配置目录：~/.anthony/
ANTHONY_HOME = Path.home() / ".anthony"
ENV_FILE = ANTHONY_HOME / ".env"

# 仅读取用户家目录下的 .env；若不存在则静默跳过（依赖系统环境变量）
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

class LLMConfig(BaseModel):
    """OpenAI 格式的模型配置"""
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-4o"))
    max_completion_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_COMPLETION_TOKENS", "4096")))
    max_input_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_INPUT_TOKENS", "128000")))
    # 当前模型是否支持视觉输入（image_url content part）。DeepSeek 等纯文本模型需设为 false
    supports_vision: bool = Field(default_factory=lambda: os.getenv("SUPPORTS_VISION", "true").lower() == "true")

class CompactConfig(BaseModel):
    """上下文压缩配置"""
    # 当 token 数超过 max_input_tokens * compact_threshold 时触发 auto_compact
    compact_threshold: float = 0.8

class Settings(BaseModel):
    """全局配置，聚合所有子配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    compact: CompactConfig = Field(default_factory=CompactConfig)

app_config = Settings()
