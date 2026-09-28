"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _app_env() -> str:
    env = os.environ.get("APP_ENV", "local").strip().lower()
    return env or "local"


@dataclass(frozen=True)
class Settings:
    app_name: str = "城市地下管网养护管理平台"
    env: str = field(default_factory=_app_env)
    port: int = 8000
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200


settings = Settings()
