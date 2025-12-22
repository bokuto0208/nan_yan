"""
排程相關的API請求和響應模型
"""
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime


class SchedulingRequest(BaseModel):
    """排程請求"""
    order_ids: Optional[List[str]] = None  # 指定訂單ID列表，空則排程所有待排程訂單
    merge_enabled: bool = True  # 啟用合併
    merge_window_weeks: int = 2  # 合併窗口（週）
    time_threshold_pct: int = 10  # 成型時間閾值(%)
    reschedule_all: bool = False  # 是否重新排程所有（包括已排程的）
    

class ScheduleBlockResponse(BaseModel):
    """排程區塊響應"""
    block_id: str
    machine_id: str
    mold_code: str
    start_time: str  # ISO格式
    end_time: str
    mo_ids: List[str]
    component_codes: List[str]
    product_display: str
    status: str
    is_merged: bool
    

class SchedulingResponse(BaseModel):
    """排程響應"""
    success: bool
    message: str
    blocks: List[ScheduleBlockResponse]
    scheduled_mos: List[str]
    failed_mos: List[str]
    total_mos: int
    on_time_count: int
    late_count: int
    total_lateness_days: float
    changeover_count: int
    delay_reports: List[Dict]
    change_log: List[str]  # 修正為 List[str]
    execution_time_seconds: float = 0

class ScheduleUpdateItem(BaseModel):
    """單個排程區塊更新"""
    id: str  # 前端使用的 ID (可能是臨時的)
    orderId: str  # 真實的訂單 ID (ComponentSchedule.id)
    productId: str  # 品號
    startHour: float
    endHour: float
    machineId: str
    scheduledDate: str
    status: Optional[str] = None
    aiLocked: Optional[bool] = None
    isModified: Optional[bool] = False  # 新增：標記是否被修改，用於同步機台

class ScheduleUpdateRequest(BaseModel):
    """批量更新請求"""
    updates: List[ScheduleUpdateItem]
    deletedIds: List[str] = []  # 要刪除的舊區塊 ID (order_id-sequence)
