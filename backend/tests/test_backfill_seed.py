"""回填修复本地样例的环境检查、生成与中断恢复测试（仅标准库）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backfill_seed as seed  # noqa: E402
from app.backfill_seed import (  # noqa: E402
    MODE_EXISTING,
    MODE_FRESH,
    MODE_RECOVERED,
    BackfillSeedError,
    build_rows,
    check_environment,
    checksum_of,
    ensure_backfill_seed,
    load_valid_rows,
    validate_rows,
)


class SeedRowTests(unittest.TestCase):
    def test_sample_rows_are_complete_and_valid(self) -> None:
        rows = build_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(validate_rows(rows), [])
        codes = [row["回填编号"] for row in rows]
        self.assertEqual(codes, ["BACK-2026-0001", "BACK-2026-0002", "BACK-2026-0003"])

    def test_required_field_missing_is_rejected(self) -> None:
        rows = build_rows()
        for field in ["回填编号", "修复路段", "管沟深度", "回填材料"]:
            broken = [dict(row) for row in rows]
            broken[0][field] = "   "
            problems = validate_rows(broken)
            self.assertTrue(any(field in item for item in problems), field)

    def test_build_is_deterministic(self) -> None:
        self.assertEqual(build_rows(), build_rows())
        self.assertEqual(checksum_of(build_rows()), checksum_of(build_rows()))


class EnvironmentCheckTests(unittest.TestCase):
    def test_writable_temp_dir_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            problems = check_environment(Path(tmp) / "nested" / "backfill.seed")
            self.assertEqual(problems, [])

    def test_state_path_blocked_by_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "backfill.seed"
            blocked.mkdir()
            problems = check_environment(blocked)
            self.assertTrue(any("非文件占用" in p for p in problems))


class EnsureSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_path = Path(self._tmp.name) / "data" / "backfill.seed"

    def test_first_run_is_fresh_and_writes_state_without_tmp(self) -> None:
        result = ensure_backfill_seed(self.state_path)
        self.assertEqual(result.mode, MODE_FRESH)
        self.assertTrue(self.state_path.is_file())
        self.assertFalse(self.state_path.with_name("backfill.seed.tmp").exists())
        self.assertEqual(validate_rows(result.rows), [])

    def test_rerun_is_existing_and_byte_identical(self) -> None:
        first = ensure_backfill_seed(self.state_path)
        before = self.state_path.read_bytes()
        second = ensure_backfill_seed(self.state_path)
        self.assertEqual(second.mode, MODE_EXISTING)
        self.assertEqual(second.rows, first.rows)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_store_sees_same_rows_across_restarts(self) -> None:
        # 模拟“启动 -> 关停 -> 再启动”：两次装载结果必须完全一致。
        from app.store import Store

        first_rows = Store().rows("backfill")
        second_rows = Store().rows("backfill")
        self.assertEqual(first_rows, second_rows)
        for row in first_rows:
            for field in ["回填编号", "修复路段", "管沟深度", "回填材料"]:
                self.assertTrue(str(row[field]).strip())

    def test_interrupted_complete_tmp_is_committed(self) -> None:
        rows = build_rows()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name("backfill.seed.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "module": "backfill",
                    "version": 1,
                    "count": len(rows),
                    "checksum": checksum_of(rows),
                    "rows": rows,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = ensure_backfill_seed(self.state_path)
        self.assertEqual(result.mode, MODE_RECOVERED)
        self.assertTrue(self.state_path.is_file())
        self.assertFalse(tmp.exists())
        self.assertEqual(load_valid_rows(self.state_path), rows)

    def test_half_baked_tmp_is_cleaned_and_regenerated(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name("backfill.seed.tmp")
        half = {"id": 9, "回填编号": "BACK-BROKEN"}  # 缺修复路段/管沟深度/回填材料
        tmp.write_text(json.dumps(half, ensure_ascii=False), encoding="utf-8")
        result = ensure_backfill_seed(self.state_path)
        self.assertEqual(result.mode, MODE_RECOVERED)
        self.assertFalse(tmp.exists())
        self.assertEqual(validate_rows(result.rows), [])

    def test_corrupted_state_file_is_rebuilt(self) -> None:
        ensure_backfill_seed(self.state_path)
        good = self.state_path.read_bytes()
        with self.state_path.open("a", encoding="utf-8") as handle:
            handle.write("被截断")
        result = ensure_backfill_seed(self.state_path)
        self.assertEqual(result.mode, MODE_RECOVERED)
        self.assertEqual(self.state_path.read_bytes(), good)
        self.assertEqual(validate_rows(result.rows), [])

    def test_tampered_checksum_triggers_rebuild(self) -> None:
        ensure_backfill_seed(self.state_path)
        envelope = json.loads(self.state_path.read_text(encoding="utf-8"))
        envelope["rows"][0]["修复路段"] = "被人手工改过"
        self.state_path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        result = ensure_backfill_seed(self.state_path)
        self.assertEqual(result.mode, MODE_RECOVERED)
        self.assertEqual(result.rows, build_rows())

    def test_write_failure_leaves_no_tmp(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_path.parent, 0o500)  # 只读目录
        self.addCleanup(lambda: os.chmod(self.state_path.parent, 0o755))
        readonly = self.state_path.parent / "x.seed"
        # root 可绕过目录权限位，环境里若以 root 运行则跳过本用例。
        if os.geteuid() == 0:
            self.skipTest("root 绕过目录只读权限")
        with self.assertRaises(BackfillSeedError):
            ensure_backfill_seed(readonly)
        self.assertFalse(self.state_path.parent.joinpath("x.seed.tmp").exists())


if __name__ == "__main__":
    unittest.main()
