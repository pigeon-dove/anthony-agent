"""Anthony Agent - 全局配置"""

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class LLMConfig(BaseModel):
    """OpenAI 格式的模型配置"""
    api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-4o"))
    max_completion_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_COMPLETION_TOKENS", "4096")))
    max_input_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_INPUT_TOKENS", "128000")))


class CompactConfig(BaseModel):
    """上下文压缩配置"""
    # 当 token 数超过 max_input_tokens * compact_threshold 时触发 auto_compact
    compact_threshold: float = 0.8


class Settings(BaseModel):
    """全局配置，聚合所有子配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    compact: CompactConfig = Field(default_factory=CompactConfig)
    project_root: Path = PROJECT_ROOT


app_config = Settings()
