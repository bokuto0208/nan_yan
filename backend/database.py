from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import enum

# 數據庫連接
DATABASE_URL = "sqlite:///./eps_system.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 訂單狀態枚舉
class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

# 訂單模型
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(String, primary_key=True)
    order_number = Column(String, nullable=False)  # 移除 unique 限制，允許一個訂單號多個品號
    customer_name = Column(String, nullable=False)
    product_code = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    due_date = Column(String, nullable=False)
    priority = Column(Integer, default=3)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    scheduled_date = Column(String, nullable=True)
    scheduled_start_time = Column(String, nullable=True)
    scheduled_end_time = Column(String, nullable=True)
    # 新增欄位
    order_date = Column(String, nullable=True)  # 接單日期
    customer_id = Column(String, nullable=True)  # 客戶編號
    order_sequence = Column(String, nullable=True)  # 訂單序
    undelivered_quantity = Column(Integer, nullable=True)  # 未交數量
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 停機時段模型
class Downtime(Base):
    __tablename__ = "downtimes"
    
    id = Column(String, primary_key=True)
    machine_id = Column(String, nullable=False)
    start_hour = Column(Float, nullable=False)
    end_hour = Column(Float, nullable=False)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# 機台產品歷史數據模型
class MachineProductHistory(Base):
    __tablename__ = "machine_product_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(String, nullable=False)
    product_code = Column(String, nullable=False)
    total_produced = Column(Integer, default=0)
    average_yield_rate = Column(Float, default=0.0)  # 0-1
    average_production_time = Column(Float, default=0.0)  # hours
    production_count = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 機台模型
class Machine(Base):
    __tablename__ = "machine"
    
    machine_id = Column(String, primary_key=True)
    area = Column(String, nullable=False)

# 產品模型 (訂單中的產品，包含0階成品和1階子件)
class Product(Base):
    __tablename__ = "products"
    
    id = Column(String, primary_key=True)
    order_id = Column(String, nullable=False)  # 關聯到訂單
    product_code = Column(String, nullable=False)  # 品號（0開頭=成品，1開頭=子件）
    quantity = Column(Integer, nullable=False)  # 訂單數量
    undelivered_quantity = Column(Integer, nullable=True)  # 未交數量（需要生產的數量）
    product_type = Column(String, nullable=True)  # 產品類型：'finished'=0階成品, 'component'=1階子件
    created_at = Column(DateTime, default=datetime.utcnow)

# 元件模型 (最小構成單位)
class Component(Base):
    __tablename__ = "components"
    
    id = Column(String, primary_key=True)
    component_code = Column(String, unique=True, nullable=False)
    component_name = Column(String, nullable=False)
    unit = Column(String, default="個")  # 單位
    estimated_production_time = Column(Float, default=1.0)  # 預估生產時間(小時)
    created_at = Column(DateTime, default=datetime.utcnow)

# BOM表 (Bill of Materials - 物料清單)
class BOM(Base):
    __tablename__ = "bom"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String, nullable=False)  # 品號ID (0開頭的成品)
    component_code = Column(String, nullable=False)  # 子件ID (1開頭的半成品)
    cavity_count = Column(Integer, nullable=False)  # 穴數 (一模X穴數 = 1/單位用量)

# 模具資料表
class MoldData(Base):
    __tablename__ = "mold_data"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String, nullable=False)  # 成品品號 (0開頭)
    component_code = Column(String, nullable=True)  # 子件品號 (1開頭)
    mold_code = Column(String, nullable=False)  # 模具編號 (6開頭)
    cavity_count = Column(Float, nullable=True)  # 一模穴數
    machine_id = Column(String, nullable=True)  # 機台編號
    avg_molding_time = Column(Float, nullable=True)  # 平均成型時間(秒)
    frequency = Column(Float, nullable=True)  # 頻率
    yield_rank = Column(String, nullable=True)  # 良率排名
    created_at = Column(DateTime, default=datetime.utcnow)

# 庫存資料表
class Inventory(Base):
    __tablename__ = "inventory"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String, nullable=False, unique=True)  # 品號 (唯一)
    quantity = Column(Integer, nullable=False, default=0)  # 庫存數量
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 元件生產排程
class ComponentSchedule(Base):
    __tablename__ = "component_schedules"
    
    id = Column(String, primary_key=True)
    order_id = Column(String, nullable=False)
    component_code = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    scheduled_date = Column(String, nullable=True)
    scheduled_start_time = Column(String, nullable=True)
    scheduled_end_time = Column(String, nullable=True)
    machine_id = Column(String, nullable=True)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 每日排程區塊表 (儲存分段後的每日工作量)
class DailyScheduleBlock(Base):
    __tablename__ = "daily_schedule_blocks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, nullable=False)  # 製令號（關聯到 ComponentSchedule.id）
    component_code = Column(String, nullable=False)  # 品號
    machine_id = Column(String, nullable=False)  # 機台
    scheduled_date = Column(String, nullable=False)  # 該段的日期 YYYY-MM-DD
    start_time = Column(DateTime, nullable=False)  # 開始時間
    end_time = Column(DateTime, nullable=False)  # 結束時間
    sequence = Column(Integer, nullable=False)  # 第幾段 (1, 2, 3...)
    total_sequences = Column(Integer, nullable=False)  # 總共幾段
    previous_block_id = Column(Integer, nullable=True)  # 前一段的 ID
    next_block_id = Column(Integer, nullable=True)  # 後一段的 ID
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 報完工資料表
class Completion(Base):
    __tablename__ = "completions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    completion_no = Column(String, nullable=False, unique=True, index=True)  # 完工單號（唯一）
    completion_date = Column(String, nullable=False)  # 完工日期
    stock_in_date = Column(String, nullable=False)    # 入庫日期
    finished_item_no = Column(String, nullable=False)  # 完工品號
    completed_qty = Column(Integer, nullable=False)    # 完工數量
    machine_code = Column(String, nullable=True)       # 機台代號
    mold_code = Column(String, nullable=True)          # 模具代號
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 0號產品對照表（成品）
class ProductZero(Base):
    __tablename__ = "product_zero"
    
    product_code = Column(String, primary_key=True)  # 品號（0開頭）
    drying_time = Column(Integer, nullable=True)  # 烘乾時間（分鐘）
    packaging_time = Column(Integer, nullable=True)  # 包裝時間（分鐘）

# 1階產品資料對照表（半成品）
class ProductOne(Base):
    __tablename__ = "product_one"
    
    product_code = Column(String, primary_key=True)  # 品號（1開頭）
    mold_change_time = Column(Integer, nullable=True)  # 換模時間（分鐘）

# 模具計算參考資料表（供排程邏輯參考用，不直接用於排程卡片）
class MoldCalculation(Base):
    __tablename__ = "mold_calculations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String, nullable=False)  # 品號
    component_code = Column(String, nullable=True)  # 子件品號
    order_total = Column(Integer, nullable=True)  # 訂單總量
    inventory_total = Column(Integer, nullable=True)  # 庫存總量
    needed_quantity = Column(Integer, nullable=True)  # 需生產量
    mold_code = Column(String, nullable=True)  # 模具編號
    machine_id = Column(String, nullable=True)  # 機台編號
    cavity_count = Column(Float, nullable=True)  # 一模穴數
    shot_count = Column(Integer, nullable=True)  # 模次
    avg_molding_time_sec = Column(Float, nullable=True)  # 平均成型時間(秒)
    mold_change_time_min = Column(Float, nullable=True)  # 換模時間(分)
    total_time_sec = Column(Float, nullable=True)  # 總成型時間(秒)
    total_time_with_change_min = Column(Float, nullable=True)  # 含換模總時間(分)
    created_at = Column(DateTime, default=datetime.utcnow)

# 工作日曆模型
class WorkCalendarDay(Base):
    __tablename__ = "work_calendar_day"
    
    work_date = Column(String, primary_key=True, nullable=False)    # 'YYYY-MM-DD'
    work_hours = Column(Float, nullable=False)                      # 0, 16, 18, 20...
    start_time = Column(String, nullable=False, default='08:00')    # 開始時間
    note = Column(String, nullable=True)                            # 備註

# 工作日曆基礎空檔（預先計算）
class WorkCalendarGap(Base):
    __tablename__ = "work_calendar_gaps"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    work_date = Column(String, nullable=False, index=True)          # 'YYYY-MM-DD'
    gap_start = Column(DateTime, nullable=False, index=True)        # 空檔開始時間
    gap_end = Column(DateTime, nullable=False)                      # 空檔結束時間
    duration_hours = Column(Float, nullable=False)                  # 持續時間（小時）
    created_at = Column(DateTime, default=datetime.utcnow)

# 模具製令表 (以模具為單位的製令)
class MoldManufacturingOrder(Base):
    __tablename__ = "mold_manufacturing_orders"
    
    id = Column(String, primary_key=True)                           # 製令ID
    mold_code = Column(String, nullable=False, index=True)          # 模具編號 (6開頭)
    component_code = Column(String, nullable=False, index=True)     # 生產的子件編號 (1開頭)
    total_quantity = Column(Integer, nullable=False)                # 合併後總需求數量
    total_rounds = Column(Integer, nullable=False)                  # 總回次
    cavity_count = Column(Integer, nullable=False)                  # 穴數
    machine_id = Column(String, nullable=True)                      # 建議機台編號
    earliest_due_date = Column(String, nullable=False)              # 最早交期 (YYYY-MM-DD)
    highest_priority = Column(Integer, nullable=False)              # 最高優先級
    scheduled_machine = Column(String, nullable=True)               # 排程機台
    scheduled_start = Column(DateTime, nullable=True)               # 排程開始時間
    scheduled_end = Column(DateTime, nullable=True)                 # 排程結束時間
    status = Column(String, default="PENDING")                      # 狀態
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# 模具製令訂單明細表 (追蹤每個訂單在模具製令中的份額)
class MoldOrderDetail(Base):
    __tablename__ = "mold_order_details"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    mold_mo_id = Column(String, nullable=False, index=True)         # 關聯到 mold_manufacturing_orders.id
    order_id = Column(String, nullable=False, index=True)           # 訂單ID
    order_number = Column(String, nullable=False)                   # 訂單號
    product_code = Column(String, nullable=False)                   # 成品品號 (0開頭)
    component_code = Column(String, nullable=True)                  # 子件品號 (1開頭) - 新增：記錄具體哪個子件
    component_quantity = Column(Integer, nullable=False)            # 此訂單需要的子件數量
    component_rounds = Column(Integer, nullable=False)              # 此訂單需要的回次
    due_date = Column(String, nullable=False)                       # 此訂單的交期
    priority = Column(Integer, nullable=False)                      # 此訂單的優先級

# 創建所有表
def init_db():
    Base.metadata.create_all(bind=engine)

# 獲取數據庫會話
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
