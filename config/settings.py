"""Anthony Agent - 全局配置"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class ModelConfig:
    """OpenAI 格式的模型配置"""
    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-4o"))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "4096")))


@dataclass
class Settings:
    """全局配置，聚合所有子配置"""
    model: ModelConfig = field(default_factory=ModelConfig)
    project_root: Path = PROJECT_ROOT


# 全局单例
settings = Settings()
