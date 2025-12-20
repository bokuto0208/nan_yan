from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# ==================== ✅ 報完工 Schema（新增） ====================

class CompletionCreate(BaseModel):
    completion_no: str
    completion_date: str
    stock_in_date: str
    finished_item_no: str
    completed_qty: int
    machine_code: Optional[str] = None
    mold_code: Optional[str] = None

class CompletionResponse(CompletionCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# ==================== 原本的 schema（完全不動） ====================

class OrderStatus(str):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class ProductItem(BaseModel):
    product_code: str
    quantity: int

class OrderBase(BaseModel):
    order_number: str
    customer_name: str
    product_code: str
    quantity: int
    due_date: str
    priority: int = 3
    status: str = "PENDING"
    scheduled_date: Optional[str] = None
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None

class OrderCreate(BaseModel):
    order_number: str
    customer_name: str
    due_date: str
    priority: int = 3
    status: str = "PENDING"
    products: List[ProductItem]

class OrderUpdate(BaseModel):
    order_number: Optional[str] = None
    customer_name: Optional[str] = None
    product_code: Optional[str] = None
    quantity: Optional[int] = None
    due_date: Optional[str] = None
    priority: Optional[int] = None
    status: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    products: Optional[List[ProductItem]] = None

class OrderResponse(OrderBase):
    id: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class DowntimeBase(BaseModel):
    machine_id: int
    start_hour: float
    end_hour: float
    date: str
    reason: Optional[str] = None

class DowntimeCreate(DowntimeBase):
    pass

class DowntimeResponse(DowntimeBase):
    id: str
    created_at: datetime
    class Config:
        from_attributes = True

class MachineProductHistoryResponse(BaseModel):
    id: int
    machine_id: int
    product_code: str
    total_produced: int
    average_yield_rate: float
    average_production_time: float
    production_count: int
    last_updated: datetime
    class Config:
        from_attributes = True

class MachineResponse(BaseModel):
    machine_id: str
    area: str
    class Config:
        from_attributes = True

class ComponentBase(BaseModel):
    component_code: str
    component_name: str
    unit: str = "個"
    estimated_production_time: float = 1.0

class ComponentCreate(ComponentBase):
    pass

class ComponentResponse(ComponentBase):
    id: str
    created_at: datetime
    class Config:
        from_attributes = True

class BOMBase(BaseModel):
    product_code: str
    component_code: str
    quantity_per_unit: float

class BOMCreate(BOMBase):
    pass

class BOMResponse(BOMBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

class ComponentScheduleResponse(BaseModel):
    id: str
    order_id: str
    component_code: str
    quantity: int
    scheduled_date: Optional[str] = None
    scheduled_start_time: Optional[str] = None
    scheduled_end_time: Optional[str] = None
    machine_id: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class OrderDetailResponse(OrderResponse):
    components: List[ComponentScheduleResponse] = []
    class Config:
        from_attributes = True
class CompletionCreate(BaseModel):
    completion_no: str
    completion_date: str
    stock_in_date: str
    finished_item_no: str
    completed_qty: int
    machine_code: str
    mold_code: str

class CompletionResponse(CompletionCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
