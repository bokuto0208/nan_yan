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

# ==================== ✅ 報完工資料表（新增） ====================
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

# ==================== 原本的模型（完全不動） ====================

class Order(Base):
    __tablename__ = "orders"
    id = Column(String, primary_key=True)
    order_number = Column(String, unique=True, nullable=False)
    customer_name = Column(String, nullable=False)
    product_code = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    due_date = Column(String, nullable=False)
    priority = Column(Integer, default=3)
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    scheduled_date = Column(String, nullable=True)
    scheduled_start_time = Column(String, nullable=True)
    scheduled_end_time = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Downtime(Base):
    __tablename__ = "downtimes"
    id = Column(String, primary_key=True)
    machine_id = Column(Integer, nullable=False)
    start_hour = Column(Float, nullable=False)
    end_hour = Column(Float, nullable=False)
    date = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class MachineProductHistory(Base):
    __tablename__ = "machine_product_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, nullable=False)
    product_code = Column(String, nullable=False)
    total_produced = Column(Integer, default=0)
    average_yield_rate = Column(Float, default=0.0)
    average_production_time = Column(Float, default=0.0)
    production_count = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Machine(Base):
    __tablename__ = "machine"
    machine_id = Column(String, primary_key=True)
    area = Column(String, nullable=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(String, primary_key=True)
    order_id = Column(String, nullable=False)
    product_code = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Component(Base):
    __tablename__ = "components"
    id = Column(String, primary_key=True)
    component_code = Column(String, unique=True, nullable=False)
    component_name = Column(String, nullable=False)
    unit = Column(String, default="個")
    estimated_production_time = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

class BOM(Base):
    __tablename__ = "bom"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String, nullable=False)
    component_code = Column(String, nullable=False)
    cavity_count = Column(Integer, nullable=False)

class MoldData(Base):
    __tablename__ = "mold_data"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_code = Column(String, nullable=False)
    component_code = Column(String, nullable=True)
    mold_code = Column(String, nullable=False)
    cavity_count = Column(Float, nullable=True)
    machine_id = Column(String, nullable=True)
    avg_molding_time = Column(Float, nullable=True)
    frequency = Column(Float, nullable=True)
    yield_rank = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

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

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
