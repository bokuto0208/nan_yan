"""
EPS 生產排程引擎 - 資料模型定義
針對半成品(1開頭品號)的排程
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum


class SchedulingStrategy(str, Enum):
    """排程策略"""
    DUE_DATE_FIRST = "due_date_first"  # 交期優先(唯一策略)


class MergeStrategy(str, Enum):
    """合併策略"""
    NO_MERGE = "no_merge"  # 不合併
    MERGE_WITHIN_DEADLINE = "merge_within_deadline"  # 交期內合併


class MOStatus(str, Enum):
    """製令狀態"""
    PENDING = "PENDING"  # 待排程
    SCHEDULED = "SCHEDULED"  # 已排程
    STARTED = "STARTED"  # 已開始
    LOCKED = "LOCKED"  # 鎖定
    COMPLETED = "COMPLETED"  # 完成


# ==================== 輸入資料模型 ====================

class ManufacturingOrder(BaseModel):
    """製令 (Manufacturing Order) - 排程最小單位"""
    id: str
    order_id: str  # 訂單ID
    component_code: str  # 半成品品號(1開頭)
    product_code: str  # 成品品號(0開頭)
    quantity: int  # 生產數量
    ship_due: datetime  # 預計出貨時間(交期基準)
    priority: int = 3  # 優先級(1-5, 1最高)
    status: MOStatus = MOStatus.PENDING
    
    # 排程結果
    scheduled_machine: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    
    # 標記
    locked: bool = False  # 是否鎖定
    must_end_at_shift_end: bool = False  # 是否必須在下班時對齊
    
    # 合併相關
    merged_with: Optional[List[str]] = None  # 合併的其他製令ID
    is_merged: bool = False


class MoldInfo(BaseModel):
    """模具資訊"""
    mold_code: str  # 模具編號(6開頭)
    component_code: str  # 半成品品號(1開頭)
    machine_id: str  # 機台編號
    cavity_count: float  # 一模穴數
    avg_molding_time: float  # 平均成型時間(秒)
    frequency: Optional[float] = None  # 頻率(上模次數)
    yield_rank: Optional[str] = None  # 良率排名


class DowntimeSlot(BaseModel):
    """停機時段"""
    id: str
    machine_id: str
    start_time: datetime
    end_time: datetime
    reason: Optional[str] = None


class WorkInterval(BaseModel):
    """工作時間區間"""
    start_time: datetime
    end_time: datetime


# ==================== 排程配置 ====================

class SchedulingConfig(BaseModel):
    """排程引擎配置"""
    # 策略
    strategy: SchedulingStrategy = SchedulingStrategy.DUE_DATE_FIRST
    merge_enabled: bool = False
    merge_strategy: MergeStrategy = MergeStrategy.NO_MERGE
    merge_window_weeks: int = Field(default=1, ge=1, le=5)  # 1-5週
    
    # Tie-break 門檻
    time_threshold_pct: int = Field(default=10, ge=10, le=30)  # 10/20/30%
    yield_threshold_pct: int = Field(default=10, ge=10, le=30)
    
    # 換模
    default_changeover_minutes: int = 30  # 預設換模時間
    changeover_forbidden_start: str = "20:00"  # 換模禁區開始
    changeover_forbidden_end: str = "01:00"  # 換模禁區結束
    
    # 工時
    shift_end_time: str = "01:00"  # 下班時間(預設01:00)
    
    # 其他
    now_datetime: datetime = Field(default_factory=datetime.now)
    max_candidates_per_machine: int = 5  # 每台機台最多保留的候選數


# ==================== 候選方案 ====================

class ScheduleCandidate(BaseModel):
    """排程候選方案"""
    mo_id: str  # 製令ID
    machine_id: str
    mold_code: str
    start_time: datetime
    end_time: datetime
    
    # 時間計算
    forming_hours: float  # 成型時間(小時)
    changeover_minutes: float  # 換模時間(分鐘)
    total_hours: float  # 總時間(小時)
    
    # 評估指標
    lateness_hours: float = 0  # 延遲時數
    lateness_days: float = 0  # 延遲天數
    is_on_time: bool = True  # 是否準時
    
    # Tie-break 指標
    yield_rank: Optional[str] = None
    frequency: Optional[float] = None
    
    # 限制檢查
    feasible: bool = True  # 是否可行
    constraint_violations: List[str] = []  # 違反的限制


class ScheduleBlock(BaseModel):
    """排程區塊 (甘特圖上的一個 block)"""
    block_id: str
    machine_id: str
    mold_code: str
    start_time: datetime
    end_time: datetime
    
    # 製令資訊
    mo_ids: List[str]  # 包含的製令ID
    component_codes: List[str]  # 半成品品號
    product_display: str  # 顯示文字 (如 "1A01/1B02")
    
    # 狀態
    status: MOStatus
    
    # 標記
    is_merged: bool = False
    is_locked: bool = False
    must_end_at_shift_end: bool = False
    has_changeover: bool = False  # 前面是否有換模
    split_part: Optional[int] = None  # 分割部分編號（1=第一段，2+=中間段，最後一個=最後一段）
    total_splits: Optional[int] = None  # 總共分割成幾段


# ==================== 排程結果 ====================

class ScheduleResult(BaseModel):
    """排程結果"""
    success: bool
    message: str
    
    # 排程區塊
    blocks: List[ScheduleBlock] = []
    
    # 製令狀態
    scheduled_mos: List[str] = []  # 已排程的製令ID
    failed_mos: List[str] = []  # 排程失敗的製令ID
    
    # KPI
    total_mos: int = 0
    on_time_count: int = 0
    late_count: int = 0
    total_lateness_days: float = 0
    changeover_count: int = 0
    
    # 延遲報告
    delay_reports: List[Dict] = []
    
    # 變更清單
    change_log: List[Dict] = []
    
    # 執行時間
    execution_time_seconds: float = 0


class DelayReport(BaseModel):
    """延遲報告"""
    mo_id: str
    component_code: str
    ship_due: datetime
    scheduled_end: datetime
    lateness_hours: float
    lateness_days: float
    reasons: List[str]  # 延遲原因


class ChangeLogEntry(BaseModel):
    """變更記錄"""
    mo_id: str
    change_type: str  # moved / rescheduled / merged
    old_machine: Optional[str] = None
    new_machine: Optional[str] = None
    old_start: Optional[datetime] = None
    new_start: Optional[datetime] = None
    reason: str  # 變更原因
