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
    machine_id = Column(Integer, nullable=False)
    start_hour = Column(Float, nullable=False)
    end_hour = Column(Float, nullable=False)
    date = Column(String, nullable=False)  # YYYY-MM-DD
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# 機台產品歷史數據模型
class MachineProductHistory(Base):
    __tablename__ = "machine_product_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, nullable=False)
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

# 產品模型 (訂單中的產品)
class Product(Base):
    __tablename__ = "products"
    
    id = Column(String, primary_key=True)
    order_id = Column(String, nullable=False)  # 關聯到訂單
    product_code = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
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
