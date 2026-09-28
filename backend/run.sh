#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# ===== 环境检查：解释器版本、虚拟环境、依赖、样例目录 =====
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "[启动失败] 需要 Python 3.10 及以上版本" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -q -r requirements.txt

# 回填修复样例引导自检：样例目录可写、模板完整，不通过不启动，避免起来后才发现半成品。
if ! .venv/bin/python -m app.backfill_bootstrap --check; then
  echo "[启动失败] 回填修复样例环境检查未通过" >&2
  exit 1
fi

exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
