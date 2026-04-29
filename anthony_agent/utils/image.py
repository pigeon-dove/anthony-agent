"""图片辅助工具 — OpenAI Vision 格式支持"""

import base64
from pathlib import Path

# OpenAI Vision 支持的图片格式
_IMAGE_EXTS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def is_image_file(path: str | Path) -> bool:
    """按扩展名判断是否为 OpenAI Vision 支持的图片格式。"""
    return Path(path).suffix.lower() in _IMAGE_EXTS


def image_to_data_url(path: str | Path) -> str:
    """将本地图片文件编码为 OpenAI Vision 格式的 data URL。

    格式：data:image/{mime};base64,{base64_data}
    """
    p = Path(path)
    mime = _IMAGE_EXTS[p.suffix.lower()]
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"
