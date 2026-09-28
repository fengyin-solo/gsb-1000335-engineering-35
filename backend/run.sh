#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt
# 本地启动依赖回填修复样例：先做环境检查、生成或中断恢复，失败则不启动服务，
# 避免查询接口看到缺字段的半成品数据。
.venv/bin/python -m app.backfill_seed
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
