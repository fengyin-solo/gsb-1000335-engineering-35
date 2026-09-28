"""回填修复本地样例：环境检查、确定性生成、原子落盘与中断恢复。

本地启动依赖这份样例数据，因此这里要保证三件事：

1. 环境检查先行：数据目录可创建、可写、路径不冲突，任一项不过就直接报错，
   绝不带着半成品往下走；
2. 样例一次生成完整：回填编号、修复路段、管沟深度、回填材料四个关键字段逐条
   校验，缺失即视为生成失败，落盘前拦下；
3. 写入可恢复：先写 ``backfill.seed.tmp`` 再原子替换为 ``backfill.seed``。
   进程被 kill 等中断会留下 tmp，下次启动按「中断恢复」处理——tmp 完整则补提
   交，tmp 是半成品则清理后重新生成；正式文件损坏同样清理重建。

样例内容全部来自常量，不读取时钟、不随机，所以首次生成、接口查询、再次运行
看到的记录完全一致。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODULE = "backfill"
STATE_VERSION = 1

# 登记/流转环节的口径与 services/backfill.py 保持一致。
REQUIRED_FIELDS = ["回填编号", "修复路段", "管沟深度", "回填材料"]
STATUS_ORDER = ["待回填", "回填中", "待检测", "已验收"]

# 状态文件放在后端根目录下的 data/，仅用于本地启动；已在 .gitignore 忽略。
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "backfill.seed"

MODE_FRESH = "fresh"            # 首次运行：全新生成
MODE_RECOVERED = "recovered"    # 中断恢复：tmp 补提交 / 半成品或坏文件清理后重建
MODE_EXISTING = "existing"      # 再次运行：正式文件校验通过，原样沿用

MODE_TEXT = {
    MODE_FRESH: "首次运行，已生成样例",
    MODE_RECOVERED: "检测到上次中断，已完成恢复",
    MODE_EXISTING: "样例已存在且校验一致，直接沿用",
}

# 固定样例：不使用日期/随机源，保证任意时刻重建结果逐字节一致。
SAMPLE_ROWS: list[dict[str, Any]] = [
    {
        "id": 1,
        "status": "待回填",
        "pending": True,
        "abnormal": False,
        "回填编号": "BACK-2026-0001",
        "修复路段": "滨河路（朝阳门—解放门段）",
        "管沟深度": "2.8m",
        "回填材料": "中粗砂分层回填",
        "压实度": "≥95%（分层检测）",
        "路面恢复": "AC-13 细粒式沥青混凝土",
        "验收日期": "2026-10-15",
        "回填状态": "待回填",
    },
    {
        "id": 2,
        "status": "回填中",
        "pending": True,
        "abnormal": True,
        "回填编号": "BACK-2026-0002",
        "修复路段": "兴华大街与园林路交叉口",
        "管沟深度": "3.2m",
        "回填材料": "级配碎石 + 石粉",
        "压实度": "≥96%（分层检测）",
        "路面恢复": "C30 水泥混凝土面层",
        "验收日期": "2026-10-08",
        "回填状态": "回填中",
    },
    {
        "id": 3,
        "status": "待检测",
        "pending": False,
        "abnormal": False,
        "回填编号": "BACK-2026-0003",
        "修复路段": "港兴三路（科技大道—海埠路段）",
        "管沟深度": "2.4m",
        "回填材料": "天然砂砾回填",
        "压实度": "≥93%（分层检测）",
        "路面恢复": "人行道透水砖恢复",
        "验收日期": "2026-09-25",
        "回填状态": "待检测",
    },
]


class BackfillSeedError(RuntimeError):
    """样例环境检查、生成或落盘失败；调用方应停下而不是带半成品继续。"""


@dataclass(frozen=True)
class SeedResult:
    rows: list[dict[str, Any]]
    mode: str
    state_path: Path
    detail: str


def _tmp_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.name + ".tmp")


def _canonical(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum_of(rows: list[dict[str, Any]]) -> str:
    """样例行的确定性摘要，用于识别文件被截断/篡改等损坏情况。"""
    return hashlib.sha256(_canonical(rows).encode("utf-8")).hexdigest()


def validate_rows(rows: Any) -> list[str]:
    """逐行校验样例完整性，返回人类可读的问题清单；空清单表示通过。"""
    problems: list[str] = []
    if not isinstance(rows, list) or not rows:
        return ["样例必须是非空记录列表"]

    seen_ids: set[int] = set()
    seen_codes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            problems.append(f"第 {index} 行不是记录对象")
            continue
        label = str(row.get("回填编号") or f"第 {index} 行")

        row_id = row.get("id")
        if not isinstance(row_id, int) or row_id <= 0:
            problems.append(f"{label} 的 id 非法")
        elif row_id in seen_ids:
            problems.append(f"{label} 的 id={row_id} 重复")
        else:
            seen_ids.add(row_id)

        for field in REQUIRED_FIELDS:
            if not str(row.get(field) or "").strip():
                problems.append(f"{label} 缺少必填字段「{field}」")

        code = str(row.get("回填编号") or "").strip()
        if code:
            if code in seen_codes:
                problems.append(f"回填编号 {code} 重复")
            seen_codes.add(code)

        status = row.get("status")
        if status not in STATUS_ORDER:
            problems.append(f"{label} 的状态「{status}」不在允许序列内")

    return problems


def build_rows() -> list[dict[str, Any]]:
    """生成确定性样例；字段不全时在落盘之前直接失败，不返回半成品。"""
    rows = [dict(row) for row in SAMPLE_ROWS]
    problems = validate_rows(rows)
    if problems:
        raise BackfillSeedError("样例数据不完整，已中止生成：" + "；".join(problems))
    return rows


def check_environment(state_path: Path) -> list[str]:
    """落盘前的环境检查：目录可建可写、状态/tmp 路径不是目录等。"""
    problems: list[str] = []
    data_dir = state_path.parent

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [f"样例目录无法创建 {data_dir}：{exc}"]

    if not data_dir.is_dir():
        return [f"样例路径不是目录：{data_dir}"]

    # 真正写一个探针文件，避免只看权限位（root、挂载等场景会看走眼）。
    probe = data_dir / f".{state_path.name}.probe"
    try:
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        probe.unlink(missing_ok=True)
        problems.append(f"样例目录不可写 {data_dir}：{exc}")

    if state_path.exists() and not state_path.is_file():
        problems.append(f"状态文件路径被非文件占用：{state_path}")
    tmp_path = _tmp_path(state_path)
    if tmp_path.exists() and not tmp_path.is_file():
        problems.append(f"临时文件路径被非文件占用：{tmp_path}")

    return problems


def _make_envelope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "module": MODULE,
        "version": STATE_VERSION,
        "count": len(rows),
        "checksum": checksum_of(rows),
        "rows": rows,
    }


def _write_atomic(state_path: Path, rows: list[dict[str, Any]]) -> None:
    """生成完整 envelope 后写 tmp、刷盘、原子替换；失败时清理 tmp。"""
    payload = _make_envelope(rows)
    tmp_path = _tmp_path(state_path)
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, state_path)
        except BaseException:
            # fdopen 失败时 fd 需手动关闭；正常路径 with 已接管。
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    except BaseException:
        # 失败清理：绝不给下一次启动留下“写了一半”的 tmp（能被识别的
        # 中断恢复场景只有进程被硬杀，那时本 except 来不及执行）。
        tmp_path.unlink(missing_ok=True)
        raise


def load_valid_rows(path: Path) -> list[dict[str, Any]] | None:
    """读取并校验状态文件/tmp；任何不一致都返回 None，交由上层清理重建。"""
    try:
        with path.open("r", encoding="utf-8") as handle:
            envelope = json.load(handle)
    except (OSError, ValueError):
        return None

    if not isinstance(envelope, dict):
        return None
    if envelope.get("module") != MODULE or envelope.get("version") != STATE_VERSION:
        return None
    rows = envelope.get("rows")
    if validate_rows(rows):
        return None
    if envelope.get("checksum") != checksum_of(rows):
        return None
    if envelope.get("count") != len(rows):
        return None
    return rows


def ensure_backfill_seed(state_path: Path | None = None) -> SeedResult:
    """按「首次运行 / 中断恢复 / 再次运行」三种情形给出同一份确定性样例。"""
    state_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
    tmp_path = _tmp_path(state_path)

    problems = check_environment(state_path)
    if problems:
        raise BackfillSeedError("环境检查未通过：" + "；".join(problems))

    # 1) 上次运行在原子替换前中断：完整 tmp 补提交，半成品 tmp 清理重建。
    if tmp_path.is_file():
        recovered = load_valid_rows(tmp_path)
        if recovered is not None:
            os.replace(tmp_path, state_path)
            return SeedResult(
                recovered, MODE_RECOVERED, state_path,
                "发现上次中断遗留的完整临时文件，已补提交为正式样例",
            )
        tmp_path.unlink(missing_ok=True)
        rows = build_rows()
        _write_atomic(state_path, rows)
        return SeedResult(
            rows, MODE_RECOVERED, state_path,
            "遗留临时文件是缺字段的半成品，已清理并重新生成完整样例",
        )

    # 2) 正式文件已存在：校验通过则原样沿用（再次运行/重启的幂等路径）。
    if state_path.is_file():
        rows = load_valid_rows(state_path)
        if rows is not None:
            return SeedResult(
                rows, MODE_EXISTING, state_path,
                "正式样例完整且校验一致，未做改动",
            )
        state_path.unlink(missing_ok=True)
        rows = build_rows()
        _write_atomic(state_path, rows)
        return SeedResult(
            rows, MODE_RECOVERED, state_path,
            "正式样例文件已损坏，已清理并重新生成",
        )

    # 3) 首次运行：生成、校验、原子落盘。
    rows = build_rows()
    _write_atomic(state_path, rows)
    return SeedResult(
        rows, MODE_FRESH, state_path,
        f"首次运行，已生成 {len(rows)} 条完整样例",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="回填修复本地样例生成与恢复")
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help="样例状态文件路径（默认 backend/data/backfill.seed）",
    )
    args = parser.parse_args(argv)

    try:
        result = ensure_backfill_seed(Path(args.state))
    except BackfillSeedError as exc:
        print(f"[backfill-seed] 失败：{exc}", file=sys.stderr)
        return 1

    print(
        f"[backfill-seed] {MODE_TEXT[result.mode]}：{result.detail}；"
        f"共 {len(result.rows)} 条记录 -> {result.state_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
