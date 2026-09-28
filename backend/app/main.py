"""城市地下管网养护管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.backfill_bootstrap import bootstrap as backfill_bootstrap
from app.config import settings
from app.routers import ROUTERS
from app.store import store

logger = logging.getLogger("uvicorn.error")

_backfill_seed: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 本地启动时补齐回填修复样例：区分首次运行、中断恢复与再次运行。
    global _backfill_seed
    _backfill_seed = backfill_bootstrap()
    if _backfill_seed.get("mode") != "skipped":
        logger.info("回填修复样例：%s（%s 条）",
                    _backfill_seed.get("mode"), _backfill_seed.get("count"))
    yield


app = FastAPI(title="城市地下管网养护管理平台", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {
        "ok": True,
        "app": settings.app_name,
        "modules": len(store.module_names()),
        "backfill_seed": _backfill_seed,
    }


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()
