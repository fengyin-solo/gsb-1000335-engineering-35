"""回填修复接口：维护回填记录，覆盖开始回填、提交检测、组织验收等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.backfill import BackfillService

router = APIRouter(prefix="/api/backfill", tags=["回填修复"])

service = BackfillService()

LIST_FIELDS = ["回填编号", "修复路段", "管沟深度", "回填材料", "压实度", "路面恢复", "验收日期", "回填状态"]
STATUSES = ["待回填", "回填中", "待检测", "已验收"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按回填编号检索"),
    status: str | None = Query(default=None, description="待回填、回填中、待检测、已验收"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按回填编号与状态过滤回填修复列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条回填记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"回填记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条回填记录，缺字段或编号冲突时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if entry is None:
        # 字段缺失统一以“缺少必填字段”提示；其余（如编号重复）原样透出。
        if errors and all(not error.endswith("已存在") for error in errors):
            return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(errors)}")
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="回填记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条回填记录执行开始回填、提交检测、组织验收；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出回填修复清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "backfill", "total": total, "items": items}
