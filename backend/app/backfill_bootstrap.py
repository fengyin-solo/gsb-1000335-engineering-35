"""回填修复样例引导：本地启动时补齐样例数据。

设计目标：
- 首次运行：生成样例并原子落盘，内存与快照一致；
- 中断恢复：上次只留下临时文件（写入未完成）时，清理半成品后重建；
- 再次运行：快照完整则原样加载，启动、查询、再次运行看到的记录完全一致；
- 失败清理：生成或落盘任一步失败，都不留下临时文件，也不污染内存数据。

样例日期相对“今天”生成，避免硬编码日期过期；记录本身一旦落盘即固定，
后续再启动直接复用，保证多次运行结果一致。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.store import store

logger = logging.getLogger("app.backfill_bootstrap")

MODULE = "backfill"
SNAPSHOT_VERSION = 1

# 快照文件里每条记录都必须具备的列，与列表接口、前端表头一致。
REQUIRED_FIELDS = ["回填编号", "修复路段", "管沟深度", "回填材料"]
SNAPSHOT_FIELDS = ["回填材料", "压实度", "路面恢复", "验收日期", "回填状态"]
ALL_FIELDS = REQUIRED_FIELDS + SNAPSHOT_FIELDS
STATUS_ORDER = ["待回填", "回填中", "待检测", "已验收"]

# 只在本地/开发环境自动补样例，生产等环境不替用户造数据。
SEED_ENVS = {"local", "dev", "development", ""}

MODE_FIRST = "first_run"          # 首次运行：无快照、无临时文件
MODE_RECOVER = "interrupted"      # 中断恢复：发现遗留临时文件
MODE_REBUILD = "rebuild"          # 快照损坏/版本不符：备份后重建
MODE_REUSE = "reuse"              # 再次运行：快照完整，原样加载


def default_data_dir() -> Path:
    """样例目录默认 backend/data，可用 BACKFILL_DATA_DIR 覆盖。"""
    override = os.environ.get("BACKFILL_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    # app/backfill_bootstrap.py -> app/ -> backend/
    return Path(__file__).resolve().parent.parent / "data"


def _snapshot_path(data_dir: Path) -> Path:
    return data_dir / "backfill_samples.json"


def _temp_path(data_dir: Path) -> Path:
    return data_dir / "backfill_samples.json.tmp"


def _corrupt_path(data_dir: Path) -> Path:
    return data_dir / "backfill_samples.json.corrupt"


def _today() -> date:
    return date.today()


def _iso(day: date) -> str:
    return day.isoformat()


def build_samples(today: date | None = None) -> list[dict[str, Any]]:
    """生成 3 条覆盖待回填、回填中、待检测的样例。

    日期相对今天计算，保证“不过期”；同一进程内结果确定。
    任何必填列都给真实值，不允许生成半成品。
    """
    today = today or _today()
    return [
        {
            "id": 1,
            "status": "待回填",
            "pending": True,
            "abnormal": False,
            "回填编号": "BACK-0001",
            "修复路段": "振兴路（人民大街—建设街）",
            "管沟深度": "2.10m",
            "回填材料": "级配砂石",
            "压实度": "≥95%",
            "路面恢复": "沥青混凝土面层",
            "验收日期": _iso(today + timedelta(days=7)),
            "回填状态": "待回填",
        },
        {
            "id": 2,
            "status": "回填中",
            "pending": True,
            "abnormal": True,
            "回填编号": "BACK-0002",
            "修复路段": "滨河路（三号码头—污水提升泵站）",
            "管沟深度": "3.40m",
            "回填材料": "中粗砂分层回填",
            "压实度": "≥93%",
            "路面恢复": "水泥混凝土面层",
            "验收日期": _iso(today + timedelta(days=3)),
            "回填状态": "回填中",
        },
        {
            "id": 3,
            "status": "待检测",
            "pending": False,
            "abnormal": False,
            "回填编号": "BACK-0003",
            "修复路段": "开发大道（高架桥西匝道—复兴门）",
            "管沟深度": "1.80m",
            "回填材料": "素土+碎石垫层",
            "压实度": "≥96%",
            "路面恢复": "透水砖人行道恢复",
            "验收日期": _iso(today - timedelta(days=1)),
            "回填状态": "待检测",
        },
    ]


def checksum(rows: list[dict[str, Any]]) -> str:
    """对记录内容做稳定哈希，供落盘后自检与跨运行比对。"""
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_rows(rows: Any) -> None:
    """校验样例记录完整可用；不通过直接抛错，由上层清理半成品。"""
    if not isinstance(rows, list) or not rows:
        raise ValueError("样例记录为空，拒绝写入半成品")
    seen_ids: set[int] = set()
    seen_codes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条样例不是记录对象")
        for field in REQUIRED_FIELDS:
            if not str(row.get(field) or "").strip():
                raise ValueError(f"第 {index} 条样例缺少必填字段「{field}」")
        for field in ALL_FIELDS:
            if field not in row:
                raise ValueError(f"第 {index} 条样例缺少字段「{field}」")
        if str(row.get("status") or "") not in STATUS_ORDER:
            raise ValueError(f"第 {index} 条样例状态非法：{row.get('status')!r}")
        row_id = int(row.get("id", 0))
        if row_id <= 0:
            raise ValueError(f"第 {index} 条样例编号缺失")
        if row_id in seen_ids:
            raise ValueError(f"样例编号 id={row_id} 重复")
        seen_ids.add(row_id)
        code = str(row["回填编号"]).strip()
        if code in seen_codes:
            raise ValueError(f"回填编号「{code}」重复")
        seen_codes.add(code)


def preflight(data_dir: Path | None = None) -> list[str]:
    """启动前环境检查；返回问题清单（空列表表示通过）。"""
    problems: list[str] = []

    import sys

    if sys.version_info < (3, 10):
        problems.append(f"需要 Python 3.10 及以上，当前为 {sys.version_info.major}.{sys.version_info.minor}")

    data_dir = data_dir or default_data_dir()
    parent = data_dir.parent if data_dir.parent.exists() else data_dir
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            problems.append(f"样例目录父路径 {parent} 无法创建：{exc}")
            return problems
    if not os.access(parent, os.W_OK):
        problems.append(f"样例目录 {data_dir} 不可写，请检查权限")
        return problems

    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        problems.append(f"样例目录 {data_dir} 不可写：{exc}")
        return problems

    try:
        _validate_rows(build_samples())
    except ValueError as exc:
        problems.append(f"样例模板自检失败：{exc}")
    return problems


def _write_snapshot_atomic(rows: list[dict[str, Any]], data_dir: Path) -> Path:
    """先写临时文件再原子改名；任一步失败都清理临时文件。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    snapshot = _snapshot_path(data_dir)
    tmp = _temp_path(data_dir)
    tmp.unlink(missing_ok=True)
    document = {"version": SNAPSHOT_VERSION, "checksum": checksum(rows), "rows": rows}
    try:
        # 先在目标目录内建临时文件，保证 rename 是同盘原子操作。
        fd, tmp_name = tempfile.mkstemp(prefix=snapshot.name + ".", suffix=".tmp", dir=data_dir)
        staged = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, snapshot)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    finally:
        # mkstemp 走的是随机名；兼容旧的固定临时名，一并兜底清理。
        tmp.unlink(missing_ok=True)
    return snapshot


def _read_snapshot(data_dir: Path) -> list[dict[str, Any]]:
    """读取并校验快照；任何不一致都抛 ValueError。"""
    snapshot = _snapshot_path(data_dir)
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("快照结构不是对象")
    if document.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"快照版本 {document.get('version')!r} 与当前 {SNAPSHOT_VERSION} 不一致")
    rows = document.get("rows")
    _validate_rows(rows)
    digest = document.get("checksum")
    actual = checksum(rows)
    if digest != actual:
        raise ValueError(f"快照校验和不一致（文件 {digest!r}，实际 {actual!r}）")
    return rows


def _quarantine_corrupt(data_dir: Path) -> None:
    snapshot = _snapshot_path(data_dir)
    if not snapshot.exists():
        return
    corrupt = _corrupt_path(data_dir)
    corrupt.unlink(missing_ok=True)
    snapshot.replace(corrupt)


def bootstrap(data_dir: Path | None = None) -> dict[str, Any]:
    """补齐回填修复样例并写入内存仓库。

    返回 {mode, count, checksum}，供健康检查/日志展示。
    非本地环境直接跳过，不创建任何文件。
    任一步失败都清理临时文件、不改动内存，并抛出 RuntimeError 说明原因。
    """
    env = os.environ.get("APP_ENV", "local").strip()
    if env not in SEED_ENVS:
        logger.info("当前环境 APP_ENV=%s，跳过回填修复样例引导", env)
        return {"mode": "skipped", "count": len(store.rows(MODULE)), "checksum": None}

    problems = preflight(data_dir)
    if problems:
        raise RuntimeError("回填修复样例环境检查未通过：" + "；".join(problems))

    data_dir = data_dir or default_data_dir()
    snapshot = _snapshot_path(data_dir)

    def _cleanup_temp() -> None:
        for stale in data_dir.glob(snapshot.name + ".*.tmp"):
            stale.unlink(missing_ok=True)
        _temp_path(data_dir).unlink(missing_ok=True)

    leftover_temp = sorted(data_dir.glob(snapshot.name + ".*.tmp")) or (
        [_temp_path(data_dir)] if _temp_path(data_dir).exists() else []
    )

    try:
        # 中断恢复：上次写入没走完，留下临时半成品，先清理再重建。
        if leftover_temp:
            for stale in leftover_temp:
                stale.unlink(missing_ok=True)
            logger.warning("检测到中断遗留的临时样例文件，已清理：%s",
                           "、".join(str(path) for path in leftover_temp))
            mode = MODE_RECOVER
            rows: list[dict[str, Any]] | None = None
            if snapshot.exists():
                try:
                    rows = _read_snapshot(data_dir)
                except ValueError:
                    rows = None
            if rows is None:
                rows = build_samples()
                _quarantine_corrupt(data_dir)
                _write_snapshot_atomic(rows, data_dir)
        elif not snapshot.exists():
            # 首次运行：什么都没有，全新生成。
            mode = MODE_FIRST
            rows = build_samples()
            _write_snapshot_atomic(rows, data_dir)
        else:
            # 再次运行：优先原样加载；快照损坏则隔离后重建。
            try:
                rows = _read_snapshot(data_dir)
                mode = MODE_REUSE
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                logger.warning("回填修复样例快照损坏（%s），备份后重建", exc)
                _quarantine_corrupt(data_dir)
                mode = MODE_REBUILD
                rows = build_samples()
                _write_snapshot_atomic(rows, data_dir)
    except (OSError, ValueError) as exc:
        # 落盘/校验失败：清掉本次留下的临时文件，内存保持原样，避免半成品。
        _cleanup_temp()
        raise RuntimeError(f"回填修复样例引导失败，已清理临时文件：{exc}") from exc

    # 内存整体替换：要么全部生效，要么不动，避免半套数据。
    store.replace_rows(MODULE, rows)
    digest = checksum(rows)
    logger.info("回填修复样例引导完成：mode=%s，记录 %d 条，checksum=%s", mode, len(rows), digest[:12])
    return {"mode": mode, "count": len(rows), "checksum": digest}


def status(data_dir: Path | None = None) -> dict[str, Any]:
    """供健康检查展示：当前快照状态与记录数。"""
    data_dir = data_dir or default_data_dir()
    snapshot = _snapshot_path(data_dir)
    if not snapshot.exists():
        return {"ready": False, "mode": None, "count": 0, "checksum": None}
    try:
        rows = _read_snapshot(data_dir)
    except (ValueError, OSError, json.JSONDecodeError):
        return {"ready": False, "mode": "corrupt", "count": 0, "checksum": None}
    return {"ready": True, "mode": MODE_REUSE, "count": len(rows), "checksum": checksum(rows)}


def main() -> int:
    """命令行入口：python -m app.backfill_bootstrap [--check]。"""
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "--check" in sys.argv[1:]:
        problems = preflight()
        if problems:
            for problem in problems:
                print(f"[环境检查失败] {problem}")
            return 1
        print("[环境检查通过] 样例目录可写，样例模板自检通过")
        info = status()
        print(f"[当前快照] {json.dumps(info, ensure_ascii=False)}")
        return 0
    info = bootstrap()
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
