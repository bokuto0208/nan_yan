from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from typing import List, Optional, Dict
import uvicorn
import uuid
import math
import os
import shutil
from datetime import datetime, timedelta
import time

from database import get_db, init_db, Order, Downtime, MachineProductHistory, Machine, Component, BOM, ComponentSchedule, Completion, Product, MoldData, MoldCalculation, WorkCalendarDay, DailyScheduleBlock
from schemas import (
    OrderCreate, OrderUpdate, OrderResponse,
    DowntimeCreate, DowntimeResponse,
    MachineProductHistoryResponse,
    MachineResponse,
    ComponentCreate, ComponentResponse,
    BOMCreate, BOMResponse,
    ComponentScheduleResponse,
    OrderDetailResponse,
    CompletionCreate, CompletionResponse
)
from schemas_scheduling import (
    SchedulingRequest,
    SchedulingResponse,
    ScheduleBlockResponse,
    ScheduleUpdateRequest,
    ScheduleUpdateItem
)
from scheduling.models import ManufacturingOrder, SchedulingConfig
from scheduling.scheduling_engine import SchedulingEngine
from scheduling.block_splitter import BlockSplitter

# ====== 輔助函數 ======

def save_daily_schedule_blocks(db: Session, blocks: list):
    """
    將排程區塊分割成每日工作段並保存到資料庫
    blocks 參數是 ScheduleBlock 對象列表（不是 Response 對象）
    """
    from scheduling.models import SchedulingConfig
    from scheduling.constraint_checker import ConstraintChecker
    
    # 清空舊的每日排程資料
    db.query(DailyScheduleBlock).delete()
    
    # 創建配置和約束檢查器
    config = SchedulingConfig()
    constraint_checker = ConstraintChecker(db, config)
    
    # 使用 BlockSplitter 分割區塊
    splitter = BlockSplitter(db, config, constraint_checker)
    
    # 直接分割所有區塊（blocks 已經是 ScheduleBlock 對象）
    all_daily_blocks = splitter.split_blocks_by_workday(blocks)
    
    # 按照 (order_id, component_code, machine_id) 分組並排序
    from collections import defaultdict
    block_groups = defaultdict(list)
    
    for block in all_daily_blocks:
        if block.mo_ids and block.component_codes:
            key = (block.mo_ids[0], block.component_codes[0], block.machine_id)
            block_groups[key].append(block)
    
    # 保存到資料庫並建立前後關聯
    for key, group_blocks in block_groups.items():
        # 按開始時間排序
        group_blocks.sort(key=lambda b: b.start_time)
        order_id, component_code, machine_id = key
        total_sequences = len(group_blocks)
        
        saved_blocks = []
        for seq, block in enumerate(group_blocks, start=1):
            daily_block = DailyScheduleBlock(
                order_id=order_id,
                component_code=component_code,
                machine_id=machine_id,
                scheduled_date=block.start_time.strftime('%Y-%m-%d'),
                start_time=block.start_time,
                end_time=block.end_time,
                sequence=seq,
                total_sequences=total_sequences,
                status="已排程"
            )
            db.add(daily_block)
            db.flush()  # 取得自動生成的 ID
            saved_blocks.append(daily_block)
        
        # 建立前後關聯
        for i, daily_block in enumerate(saved_blocks):
            if i > 0:
                daily_block.previous_block_id = saved_blocks[i-1].id
            if i < len(saved_blocks) - 1:
                daily_block.next_block_id = saved_blocks[i+1].id
    
    db.commit()
    print(f"✅ 已保存 {len(all_daily_blocks)} 個每日排程區塊")

def check_product_warning(product_code: str, db: Session) -> str:
    """檢查品號是否有排程資料缺失"""
    # 查詢模具資料
    mold = db.query(MoldData).filter(MoldData.product_code == product_code).first()
    
    if not mold:
        return "無模具資料"
    
    if not mold.mold_code:
        return "無模具資料"
    
    if not mold.mold_code.startswith('6'):
        return "模具編號不正確"
    
    if not mold.machine_id or not mold.cavity_count or mold.cavity_count <= 0:
        return "機台編號或穴數資料不完整"
    
    return ""

def check_component_can_schedule(component_code: str, db: Session) -> bool:
    """檢查子件（1開頭）是否有足夠的模具資料可以排程"""
    # 從 mold_calculations 查詢該子件的模具資料
    mold_count = db.query(MoldCalculation).filter(
        MoldCalculation.component_code == component_code,
        MoldCalculation.machine_id.isnot(None),
        MoldCalculation.cavity_count.isnot(None),
        MoldCalculation.cavity_count > 0,
        MoldCalculation.avg_molding_time_sec.isnot(None),
        MoldCalculation.avg_molding_time_sec > 0
    ).count()
    
    return mold_count > 0

def update_undelivered_quantity(db: Session, product_code: str, completed_qty: int):
    """
    更新產品的未交數量
    當報完工時，扣除對應產品的未交數量
    """
    # 查找所有符合品號的產品記錄（可能跨多個訂單）
    products = db.query(Product).filter(
        Product.product_code == product_code,
        Product.undelivered_quantity > 0
    ).order_by(Product.created_at).all()
    
    if not products:
        print(f"⚠️ 警告: 找不到品號 {product_code} 的待生產記錄")
        return
    
    remaining = completed_qty
    updated_count = 0
    
    for product in products:
        if remaining <= 0:
            break
            
        if product.undelivered_quantity >= remaining:
            # 這筆訂單足夠扣除
            product.undelivered_quantity -= remaining
            updated_count += 1
            print(f"✓ 品號 {product_code} (訂單 {product.order_id[:8]}...) 未交數量: {product.undelivered_quantity + remaining} → {product.undelivered_quantity}")
            remaining = 0
        else:
            # 這筆訂單不夠，全部扣完後繼續下一筆
            remaining -= product.undelivered_quantity
            print(f"✓ 品號 {product_code} (訂單 {product.order_id[:8]}...) 未交數量: {product.undelivered_quantity} → 0")
            product.undelivered_quantity = 0
            updated_count += 1
    
    if remaining > 0:
        print(f"⚠️ 警告: 品號 {product_code} 完工數量超過未交數量，剩餘 {remaining} 未扣除")
    
    db.flush()
    return updated_count

# ====== FastAPI 應用 ======

# 初始化 FastAPI 應用
app = FastAPI(title="EPS System API", version="1.0.0")

# CORS 設置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發環境允許所有來源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 啟動時初始化數據庫
@app.on_event("startup")
def startup_event():
    init_db()
    print("✅ Database initialized")

# 健康檢查
@app.get("/")
def read_root():
    return {"status": "ok", "message": "EPS System API is running"}

# ==================== 訂單管理 API ====================

@app.get("/api/orders", response_model=List[OrderResponse])
def get_orders(db: Session = Depends(get_db)):
    """獲取所有訂單"""
    orders = db.query(Order).all()
    return orders

@app.get("/api/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, db: Session = Depends(get_db)):
    """獲取單個訂單"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.post("/api/orders", response_model=OrderResponse)
def create_order(order_data: OrderCreate, db: Session = Depends(get_db)):
    """創建新訂單（包含產品列表）並自動拆解成子件"""
    from database import Product
    
    # 檢查訂單號是否已存在
    existing = db.query(Order).filter(Order.order_number == order_data.order_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Order number already exists")
    
    # 使用第一個產品的資訊作為主要訂單資訊（向後兼容）
    first_product = order_data.products[0] if order_data.products else None
    if not first_product:
        raise HTTPException(status_code=400, detail="At least one product is required")
    
    # 創建新訂單
    new_order = Order(
        id=str(uuid.uuid4()),
        order_number=order_data.order_number,
        customer_name=order_data.customer_name,
        product_code=first_product.product_code,  # 主要產品代碼
        quantity=first_product.quantity,          # 主要產品數量
        due_date=order_data.due_date,
        priority=order_data.priority,
        status=order_data.status
    )
    db.add(new_order)
    db.flush()  # 確保訂單 ID 可用
    
    # 創建產品記錄
    for product in order_data.products:
        new_product = Product(
            id=str(uuid.uuid4()),
            order_id=new_order.id,
            product_code=product.product_code,
            quantity=product.quantity
        )
        db.add(new_product)
    
    db.flush()  # 確保產品記錄可用
    
    # 自動拆解成子件
    component_summary = {}  # 用於合併相同元件
    
    for product in order_data.products:
        # 查詢該產品的BOM
        bom_items = db.query(BOM).filter(BOM.product_code == product.product_code).all()
        
        if bom_items:
            # 為每個BOM項目計算所需數量
            for bom_item in bom_items:
                # 數量計算：產品數量 / 穴數（無條件進位）
                # 穴數是模具一次可以生產的產品數量
                required_quantity = math.ceil(product.quantity / bom_item.cavity_count)
                
                # 合併相同元件的數量
                if bom_item.component_code in component_summary:
                    component_summary[bom_item.component_code] += required_quantity
                else:
                    component_summary[bom_item.component_code] = required_quantity
    
    # 創建元件排程記錄
    for component_code, total_quantity in component_summary.items():
        # 判斷狀態：6開頭=模具,數量為0=無法排程,其他檢查模具資料
        if component_code.startswith('6'):
            status = "模具"
        elif total_quantity == 0:
            status = "無法進行排程"
        else:
            can_schedule = check_component_can_schedule(component_code, db)
            status = "未排程" if can_schedule else "無法進行排程"
        
        component_schedule = ComponentSchedule(
            id=str(uuid.uuid4()),
            order_id=new_order.id,
            component_code=component_code,
            quantity=total_quantity,
            status=status
        )
        db.add(component_schedule)
    
    db.commit()
    db.refresh(new_order)
    
    print(f"✓ Created order {new_order.order_number} with {len(component_summary)} components")
    
    return new_order

@app.put("/api/orders/{order_id}", response_model=OrderResponse)
def update_order(order_id: str, order_data: OrderUpdate, db: Session = Depends(get_db)):
    """更新訂單"""
    from database import Product
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # 更新基本字段
    update_data = order_data.model_dump(exclude_unset=True, exclude={'products'})
    for key, value in update_data.items():
        setattr(order, key, value)
    
    # 如果有產品列表，更新產品並重新生成元件排程
    if order_data.products is not None:
        # 刪除舊的產品記錄
        db.query(Product).filter(Product.order_id == order_id).delete()
        
        # 刪除舊的元件排程記錄
        db.query(ComponentSchedule).filter(ComponentSchedule.order_id == order_id).delete()
        
        # 創建新的產品記錄
        for product in order_data.products:
            new_product = Product(
                id=str(uuid.uuid4()),
                order_id=order_id,
                product_code=product.product_code,
                quantity=product.quantity
            )
            db.add(new_product)
        
        db.flush()  # 確保產品記錄可用
        
        # 更新訂單的主要產品資訊（使用第一個產品）
        if order_data.products:
            first_product = order_data.products[0]
            order.product_code = first_product.product_code
            order.quantity = first_product.quantity
        
        # 重新拆解成子件
        component_summary = {}  # 用於合併相同元件
        
        for product in order_data.products:
            # 查詢該產品的BOM
            bom_items = db.query(BOM).filter(BOM.product_code == product.product_code).all()
            
            if bom_items:
                # 為每個BOM項目計算所需數量
                for bom_item in bom_items:
                    # 數量計算：產品數量 / 穴數（無條件進位）
                    # 穴數是模具一次可以生產的產品數量
                    required_quantity = math.ceil(product.quantity / bom_item.cavity_count)
                    
                    # 合併相同元件的數量
                    if bom_item.component_code in component_summary:
                        component_summary[bom_item.component_code] += required_quantity
                    else:
                        component_summary[bom_item.component_code] = required_quantity
        
        # 創建元件排程記錄
        for component_code, total_quantity in component_summary.items():
            # 判斷狀態：6開頭=模具，數量為0=無法排程，其他檢查模具資料
            if component_code.startswith('6'):
                status = "模具"
            elif total_quantity == 0:
                status = "無法進行排程"
            else:
                can_schedule = check_component_can_schedule(component_code, db)
                status = "未排程" if can_schedule else "無法進行排程"
            
            component_schedule = ComponentSchedule(
                id=str(uuid.uuid4()),
                order_id=order_id,
                component_code=component_code,
                quantity=total_quantity,
                status=status
            )
            db.add(component_schedule)
    
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order

@app.delete("/api/orders/{order_number}")
def delete_order(order_number: str, db: Session = Depends(get_db)):
    """刪除訂單（根據訂單號刪除該訂單號的所有記錄）"""
    orders = db.query(Order).filter(Order.order_number == order_number).all()
    if not orders:
        raise HTTPException(status_code=404, detail="Order not found")
    
    deleted_count = len(orders)
    for order in orders:
        db.delete(order)
    db.commit()
    return {"message": f"Order deleted successfully (deleted {deleted_count} records)"}

@app.delete("/api/orders/all/delete")
def delete_all_orders(db: Session = Depends(get_db)):
    """刪除所有訂單及相關資料"""
    try:
        # 刪除相關資料
        deleted_schedules = db.query(ComponentSchedule).delete()
        deleted_blocks = db.query(DailyScheduleBlock).delete()
        deleted_products = db.query(Product).delete()
        deleted_orders = db.query(Order).delete()
        
        db.commit()
        
        return {
            "message": "所有訂單已刪除",
            "deleted": {
                "orders": deleted_orders,
                "component_schedules": deleted_schedules,
                "schedule_blocks": deleted_blocks,
                "products": deleted_products
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"刪除失敗: {str(e)}")

@app.post("/api/orders/import-excel")
async def import_orders_excel(file: UploadFile = File(...)):
    """從 Excel 匯入訂單"""
    from import_orders_excel import import_orders_from_excel
    
    # 檢查文件類型
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="只支援 Excel 文件 (.xlsx, .xls)")
    
    # 保存上傳的文件
    temp_file = f"temp_{file.filename}"
    try:
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 執行匯入
        result = import_orders_from_excel(temp_file)
        
        return {
            "message": "匯入成功",
            "imported": result["imported"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "warnings": result.get("warnings", [])
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"匯入失敗: {str(e)}")
    finally:
        # 刪除臨時文件
        if os.path.exists(temp_file):
            os.remove(temp_file)

@app.post("/api/orders/bootstrap")
def bootstrap_sample_data(db: Session = Depends(get_db)):
    """初始化示例數據"""
    # 清除現有訂單
    db.query(Order).delete()
    
    # 創建示例訂單
    sample_orders = [
        {
            "id": str(uuid.uuid4()),
            "order_number": "ORD-001",
            "customer_name": "客戶 A",
            "product_code": "P001",
            "quantity": 500,
            "due_date": "2024-12-15",
            "priority": 1,
            "status": "PENDING"
        },
        {
            "id": str(uuid.uuid4()),
            "order_number": "ORD-002",
            "customer_name": "客戶 B",
            "product_code": "P002",
            "quantity": 300,
            "due_date": "2024-12-20",
            "priority": 2,
            "status": "PENDING"
        },
        {
            "id": str(uuid.uuid4()),
            "order_number": "ORD-003",
            "customer_name": "客戶 C",
            "product_code": "P003",
            "quantity": 800,
            "due_date": "2024-12-18",
            "priority": 1,
            "status": "SCHEDULED"
        }
    ]
    
    for order_data in sample_orders:
        order = Order(**order_data)
        db.add(order)
    
    db.commit()
    return {"message": f"Created {len(sample_orders)} sample orders"}

# ==================== 停機時段管理 API ====================

@app.get("/api/downtimes", response_model=List[DowntimeResponse])
def get_downtimes(date: str = None, db: Session = Depends(get_db)):
    """獲取停機時段（可選按日期篩選）"""
    query = db.query(Downtime)
    if date:
        query = query.filter(Downtime.date == date)
    return query.all()

@app.post("/api/downtimes", response_model=DowntimeResponse)
def create_downtime(downtime_data: DowntimeCreate, db: Session = Depends(get_db)):
    """創建停機時段"""
    new_downtime = Downtime(
        id=f"down-{uuid.uuid4()}",
        **downtime_data.model_dump()
    )
    db.add(new_downtime)
    db.commit()
    db.refresh(new_downtime)
    return new_downtime

@app.delete("/api/downtimes/{downtime_id}")
def delete_downtime(downtime_id: str, db: Session = Depends(get_db)):
    """刪除停機時段"""
    downtime = db.query(Downtime).filter(Downtime.id == downtime_id).first()
    if not downtime:
        raise HTTPException(status_code=404, detail="Downtime not found")
    
    db.delete(downtime)
    db.commit()
    return {"message": "Downtime deleted successfully"}

# ==================== 報完工 API ====================

@app.post("/api/completions", response_model=CompletionResponse)
def create_completion(data: CompletionCreate, db: Session = Depends(get_db)):
    """建立報完工記錄"""
    # 檢查完工單號是否已存在（唯一）
    existing = db.query(Completion).filter(
        Completion.completion_no == data.completion_no
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"completion_no '{data.completion_no}' already exists"
        )
    
    # 不存在才新增
    new_row = Completion(**data.model_dump())
    db.add(new_row)
    
    # 更新對應產品的未交數量
    update_undelivered_quantity(db, data.finished_item_no, data.completed_qty)
    
    db.commit()
    db.refresh(new_row)
    return new_row

@app.post("/api/completions/batch")
def create_completions_batch(
    payloads: List[CompletionCreate],
    db: Session = Depends(get_db)
) -> Dict:
    """批次建立報完工記錄"""
    inserted = 0
    skipped = 0
    skipped_nos: List[str] = []
    
    for payload in payloads:
        try:
            # 檢查完工單號是否已存在
            exists = db.query(Completion).filter(
                Completion.completion_no == payload.completion_no
            ).first()
            if exists:
                skipped += 1
                skipped_nos.append(payload.completion_no)
                continue
            
            row = Completion(**payload.model_dump())
            db.add(row)
            db.flush()  # 讓唯一值錯誤能在這裡被抓到
            
            # 更新對應產品的未交數量
            update_undelivered_quantity(db, payload.finished_item_no, payload.completed_qty)
            
            inserted += 1
        
        except IntegrityError:
            db.rollback()
            skipped += 1
            skipped_nos.append(payload.completion_no)
    
    db.commit()
    return {
        "inserted": inserted,
        "skipped": skipped,
        "skipped_completion_nos": skipped_nos
    }

@app.get("/api/completions", response_model=List[CompletionResponse])
def get_completions(db: Session = Depends(get_db)):
    """取得所有報完工記錄"""
    return db.query(Completion).all()

@app.delete("/api/completions/all")
def delete_all_completions(db: Session = Depends(get_db)):
    """刪除所有報完工記錄"""
    count = db.query(Completion).count()
    db.query(Completion).delete()
    db.commit()
    return {"deleted_count": count, "message": f"已刪除 {count} 筆報完工資料"}

# ==================== 機台產品歷史數據 API ====================

@app.get("/api/machine-history", response_model=List[MachineProductHistoryResponse])
def get_machine_history(
    machine_id: int = None,
    product_code: str = None,
    db: Session = Depends(get_db)
):
    """獲取機台產品歷史數據"""
    query = db.query(MachineProductHistory)
    if machine_id:
        query = query.filter(MachineProductHistory.machine_id == machine_id)
    if product_code:
        query = query.filter(MachineProductHistory.product_code == product_code)
    return query.all()

# ==================== 機台管理 API ====================

@app.get("/api/machines", response_model=List[MachineResponse])
def get_machines(area: Optional[str] = None, db: Session = Depends(get_db)):
    """取得機台列表，可依區域篩選"""
    query = db.query(Machine)
    if area:
        query = query.filter(Machine.area == area)
    return query.all()

@app.get("/api/machines/areas")
def get_areas(db: Session = Depends(get_db)):
    """取得所有區域列表"""
    areas = db.query(Machine.area).distinct().all()
    return {"areas": [area[0] for area in areas]}

# ==================== 元件管理 API ====================

@app.get("/api/components", response_model=List[ComponentResponse])
def get_components(db: Session = Depends(get_db)):
    """獲取所有元件"""
    return db.query(Component).all()

@app.post("/api/components", response_model=ComponentResponse)
def create_component(component_data: ComponentCreate, db: Session = Depends(get_db)):
    """創建元件"""
    new_component = Component(
        id=str(uuid.uuid4()),
        **component_data.model_dump()
    )
    db.add(new_component)
    db.commit()
    db.refresh(new_component)
    return new_component

# ==================== BOM管理 API ====================

@app.get("/api/bom", response_model=List[BOMResponse])
def get_bom(product_code: Optional[str] = None, db: Session = Depends(get_db)):
    """獲取BOM表，可按產品篩選"""
    query = db.query(BOM)
    if product_code:
        query = query.filter(BOM.product_code == product_code)
    return query.all()

@app.post("/api/bom", response_model=BOMResponse)
def create_bom(bom_data: BOMCreate, db: Session = Depends(get_db)):
    """創建BOM條目"""
    new_bom = BOM(**bom_data.model_dump())
    db.add(new_bom)
    db.commit()
    db.refresh(new_bom)
    return new_bom

# ==================== 訂單詳細資訊 (包含元件) ====================

@app.get("/api/orders/{order_id}/detail", response_model=OrderDetailResponse)
def get_order_detail(order_id: str, db: Session = Depends(get_db)):
    """獲取訂單詳細資訊，包含所有需要生產的元件"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # 查詢該訂單的元件排程
    component_schedules = db.query(ComponentSchedule).filter(
        ComponentSchedule.order_id == order_id
    ).all()
    
    # 構建響應
    order_dict = {
        "id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "product_code": order.product_code,
        "quantity": order.quantity,
        "due_date": order.due_date,
        "priority": order.priority,
        "status": order.status,
        "scheduled_date": order.scheduled_date,
        "scheduled_start_time": order.scheduled_start_time,
        "scheduled_end_time": order.scheduled_end_time,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "components": component_schedules
    }
    
    return order_dict

@app.get("/api/orders-with-components")
def get_orders_with_components(db: Session = Depends(get_db)):
    """獲取所有訂單及其產品和子件"""
    from database import Product, Inventory
    
    orders = db.query(Order).all()
    result = []
    
    for order in orders:
        # 獲取該訂單的所有產品
        products = db.query(Product).filter(Product.order_id == order.id).all()
        
        # 查詢該訂單主品號的庫存數量
        inventory_record = db.query(Inventory).filter(
            Inventory.product_code == order.product_code
        ).first()
        inventory_qty = inventory_record.quantity if inventory_record else 0
        
        # 檢查訂單主品號是否有排程資料缺失
        order_warning = check_product_warning(order.product_code, db)
        
        # 為每個產品獲取其對應的子件
        products_with_components = []
        for product in products:
            # 查詢該產品對應的子件（從 component_schedules 和 BOM 關聯）
            bom_items = db.query(BOM).filter(BOM.product_code == product.product_code).all()
            
            components_list = []
            for bom_item in bom_items:
                # 查找對應的 component_schedule
                comp_schedule = db.query(ComponentSchedule).filter(
                    ComponentSchedule.order_id == order.id,
                    ComponentSchedule.component_code == bom_item.component_code
                ).first()
                
                if comp_schedule:
                    components_list.append({
                        "component_code": comp_schedule.component_code,
                        "quantity": comp_schedule.quantity,
                        "cavity_count": bom_item.cavity_count,
                        "status": comp_schedule.status
                    })
            
            products_with_components.append({
                "product_code": product.product_code,
                "quantity": product.quantity,
                "components": components_list
            })
        
        order_dict = {
            "id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "customer_id": order.customer_id,
            "product_code": order.product_code,
            "quantity": order.quantity,
            "undelivered_quantity": order.undelivered_quantity,
            "inventory_quantity": inventory_qty,
            "due_date": order.due_date,
            "priority": order.priority,
            "status": order.status,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "products": products_with_components,
            "warning": order_warning
        }
        
        result.append(order_dict)
    
    return result

@app.post("/api/orders/{order_id}/expand-components")
def expand_order_components(order_id: str, db: Session = Depends(get_db)):
    """展開訂單的元件（根據BOM表和訂單產品自動生成元件排程）"""
    from database import Product
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # 獲取該訂單的所有產品
    products = db.query(Product).filter(Product.order_id == order_id).all()
    
    if not products:
        raise HTTPException(status_code=404, detail="No products found for this order")
    
    # 刪除舊的元件排程
    db.query(ComponentSchedule).filter(ComponentSchedule.order_id == order_id).delete()
    
    # 為每個產品的元件創建排程
    created_count = 0
    component_summary = {}  # 用於合併相同元件
    
    for product in products:
        # 查詢該產品的BOM
        bom_items = db.query(BOM).filter(BOM.product_code == product.product_code).all()
        
        if not bom_items:
            print(f"Warning: No BOM found for product {product.product_code}")
            continue
        
        # 為每個BOM項目計算所需數量
        for bom_item in bom_items:
            # 數量計算：產品數量 * 穴數
            # 穴數表示一模可以生產多少個子件，所以需要的子件數量 = 產品數量 * 穴數
            required_quantity = product.quantity * bom_item.cavity_count
            
            # 合併相同元件的數量
            if bom_item.component_code in component_summary:
                component_summary[bom_item.component_code] += required_quantity
            else:
                component_summary[bom_item.component_code] = required_quantity
    
    # 創建元件排程記錄
    for component_code, total_quantity in component_summary.items():
        # 判斷狀態：6開頭=模具，數量為0=無法排程，其他檢查模具資料
        if component_code.startswith('6'):
            status = "模具"
        elif total_quantity == 0:
            status = "無法進行排程"
        else:
            can_schedule = check_component_can_schedule(component_code, db)
            status = "未排程" if can_schedule else "無法進行排程"
        
        component_schedule = ComponentSchedule(
            id=str(uuid.uuid4()),
            order_id=order.id,
            component_code=component_code,
            quantity=total_quantity,
            status=status
        )
        db.add(component_schedule)
        created_count += 1
    
    db.commit()
    return {
        "message": f"Expanded {created_count} components for order {order.order_number}",
        "order_id": order_id,
        "components_created": created_count
    }

# ====== 工作日曆 API ======

@app.get("/api/work-calendar")
def get_work_calendar(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """獲取工作日曆資料"""
    query = db.query(WorkCalendarDay)
    
    if year and month:
        # 過濾特定年月
        start_date = f"{year:04d}-{month:02d}-01"
        # 計算下個月的第一天
        if month == 12:
            next_month = f"{year+1:04d}-01-01"
        else:
            next_month = f"{year:04d}-{month+1:02d}-01"
        query = query.filter(
            WorkCalendarDay.work_date >= start_date,
            WorkCalendarDay.work_date < next_month
        )
    
    calendar_days = query.all()
    return [
        {
            "work_date": day.work_date,
            "work_hours": day.work_hours,
            "start_time": day.start_time,
            "note": day.note
        }
        for day in calendar_days
    ]

@app.post("/api/work-calendar")
def upsert_work_calendar_day(
    data: dict,
    db: Session = Depends(get_db)
):
    """新增或更新工作日曆的某一天"""
    from calendar_gap_generator import generate_gaps_for_date
    
    work_date = data.get("work_date")
    work_hours = data.get("work_hours", 0)
    start_time = data.get("start_time", "08:00")
    note = data.get("note", "")
    
    if not work_date:
        raise HTTPException(status_code=400, detail="work_date is required")
    
    # 查找是否已存在
    existing = db.query(WorkCalendarDay).filter(
        WorkCalendarDay.work_date == work_date
    ).first()
    
    if existing:
        # 更新（覆蓋）
        existing.work_hours = work_hours
        existing.start_time = start_time
        existing.note = note
    else:
        # 新增
        new_day = WorkCalendarDay(
            work_date=work_date,
            work_hours=work_hours,
            start_time=start_time,
            note=note
        )
        db.add(new_day)
    
    db.commit()
    
    # 自動生成該日期的基礎空檔
    gap_count = generate_gaps_for_date(db, work_date)
    
    return {
        "message": "Work calendar day saved successfully",
        "gaps_generated": gap_count
    }

@app.post("/api/work-calendar/batch")
def batch_upsert_work_calendar(
    data: dict,
    db: Session = Depends(get_db)
):
    """批量新增或更新工作日曆"""
    from calendar_gap_generator import generate_gaps_for_date
    
    days = data.get("days", [])
    gap_count = 0
    
    for day_data in days:
        work_date = day_data.get("work_date")
        work_hours = day_data.get("work_hours", 0)
        start_time = day_data.get("start_time", "08:00")
        note = day_data.get("note", "")
        
        if not work_date:
            continue
        
        existing = db.query(WorkCalendarDay).filter(
            WorkCalendarDay.work_date == work_date
        ).first()
        
        if existing:
            # 更新（覆蓋）
            existing.work_hours = work_hours
            existing.start_time = start_time
            existing.note = note
        else:
            # 新增
            new_day = WorkCalendarDay(
                work_date=work_date,
                work_hours=work_hours,
                start_time=start_time,
                note=note
            )
            db.add(new_day)
    
    db.commit()
    
    # 批量生成基礎空檔
    for day_data in days:
        work_date = day_data.get("work_date")
        if work_date:
            gap_count += generate_gaps_for_date(db, work_date)
    
    return {
        "message": f"Batch saved {len(days)} work calendar days",
        "gaps_generated": gap_count
    }


# ====== 排程 API ======

@app.get("/api/scheduling/schedules")
def get_scheduled_components(date: Optional[str] = None, machine_id: Optional[str] = None, db: Session = Depends(get_db)):
    base_q = db.query(DailyScheduleBlock).filter(DailyScheduleBlock.status == "已排程")

    if date:
        # 只查詢該日期的區塊，不要跨日回傳
        query = base_q.filter(DailyScheduleBlock.scheduled_date == date)
        if machine_id:
            query = query.filter(DailyScheduleBlock.machine_id == machine_id)
    else:
        query = base_q
        if machine_id:
            query = query.filter(DailyScheduleBlock.machine_id == machine_id)

    daily_blocks = query.order_by(DailyScheduleBlock.order_id, DailyScheduleBlock.sequence).all()

    # 查詢所有相關訂單的訂單編號
    order_ids = list(set([b.order_id for b in daily_blocks]))
    orders_map = {}
    if order_ids:
        orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
        orders_map = {order.id: order.order_number for order in orders}
    
    # 轉換為前端格式
    result = []
    for block in daily_blocks:
        # 計算小時偏移量（相對於 scheduled_date 的 0點）
        base_date = datetime.strptime(block.scheduled_date, "%Y-%m-%d")
        
        # 計算開始時間的小時數
        start_diff = block.start_time - base_date
        start_hour = start_diff.total_seconds() / 3600
        
        # 計算結束時間的小時數
        end_diff = block.end_time - base_date
        end_hour = end_diff.total_seconds() / 3600
        
        # 獲取訂單編號
        order_number = orders_map.get(block.order_id, block.order_id[:8])
        
        result.append({
            "id": f"{block.order_id}-{block.sequence}",
            "orderId": order_number,  # 顯示訂單編號而不是 UUID
            "originalOrderId": block.order_id,  # 保留原始 order_id 供更新使用
            "productId": block.component_code,
            "machineId": block.machine_id,
            "startHour": start_hour,
            "endHour": end_hour,
            "scheduledDate": block.scheduled_date,
            "status": "running",
            "aiLocked": True,
            "isSplit": block.total_sequences > 1,
            "splitPart": block.sequence,
            "totalSplits": block.total_sequences
        })
    
    return {"schedules": result}


@app.put("/api/scheduling/schedules/batch")
def update_schedules(request: ScheduleUpdateRequest, db: Session = Depends(get_db)):
    """
    正確版本（最終）：
    - 同一 orderId 視為「一條時間鏈」
    - 拖動任一段：
      1. 所有 machine_id 同步
      2. 被拖動段採用新時間
      3. 後續段全部順延（接在前一段後）
      4. 不允許時間重疊
    """

    from datetime import datetime, timedelta
    from collections import defaultdict

    grouped = defaultdict(list)
    for u in request.updates:
        grouped[u.orderId].append(u)

    try:
        for order_id, updates in grouped.items():

            # 1️⃣ 找 anchor
            anchor = next((u for u in updates if getattr(u, "isModified", False)), None)
            if not anchor:
                continue

            target_machine = anchor.machineId

            # 2️⃣ 撈 DB blocks（順序很重要）
            blocks = db.query(DailyScheduleBlock).filter(
                DailyScheduleBlock.order_id == order_id
            ).order_by(DailyScheduleBlock.sequence).all()

            if not blocks:
                continue

            # 3️⃣ 統一 machine_id
            for b in blocks:
                b.machine_id = target_machine

            # 4️⃣ 找 anchor block
            anchor_block = next(
                (b for b in blocks if f"{b.order_id}-{b.sequence}" == anchor.id),
                None
            )
            if not anchor_block:
                continue

            # 5️⃣ hour → datetime
            base_date = datetime.strptime(anchor.scheduledDate, "%Y-%m-%d")

            def hour_to_dt(hour):
                d = int(hour // 24)
                h = int(hour % 24)
                m = int((hour * 60) % 60)
                return base_date + timedelta(days=d, hours=h, minutes=m)

            new_start = hour_to_dt(anchor.startHour)
            new_end = hour_to_dt(anchor.endHour)

            anchor_block.start_time = new_start
            anchor_block.end_time = new_end

            # 6️⃣ 關鍵：後續段「接龍順延」
            prev = anchor_block
            for b in blocks:
                if b.sequence <= anchor_block.sequence:
                    continue

                duration = b.end_time - b.start_time
                b.start_time = prev.end_time
                b.end_time = b.start_time + duration
                prev = b

            # 7️⃣ scheduled_date 修正（08:00 規則）
            for b in blocks:
                if b.start_time.hour < 8:
                    b.scheduled_date = (b.start_time.date() - timedelta(days=1)).isoformat()
                else:
                    b.scheduled_date = b.start_time.date().isoformat()

        db.commit()

        return {
            "success": True,
            "message": "同步完成（時間鏈順延 + 機台一致）"
        }

    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e)
        }





@app.post("/api/scheduling/run", response_model=SchedulingResponse)
def run_scheduling(
    request: SchedulingRequest,
    db: Session = Depends(get_db)
):
    """
    執行生產排程
    
    - 將待排程訂單轉換為製令
    - 使用排程引擎生成排程結果
    - 將結果保存到 ComponentSchedule 表
    """
    start_time = time.time()
    
    try:
        # 1. 獲取待排程訂單
        query = db.query(Order)
        
        # 如果指定了訂單ID，只排這些訂單
        if request.order_ids:
            query = query.filter(Order.order_number.in_(request.order_ids))
        else:
            # 否則排程所有未完成的訂單（狀態不是已完成）
            query = query.filter(Order.status != "已完成")
        
        orders = query.all()
        
        if not orders:
            return SchedulingResponse(
                success=False,
                message="沒有需要排程的訂單",
                blocks=[],
                scheduled_mos=[],
                failed_mos=[],
                total_mos=0,
                on_time_count=0,
                late_count=0,
                total_lateness_days=0,
                changeover_count=0,
                delay_reports=[],
                change_log=[],
                execution_time_seconds=0
            )
        
        # 2. 從 ComponentSchedule 轉換為製令
        mos = []
        query = db.query(ComponentSchedule).filter(
            ComponentSchedule.order_id.in_([o.id for o in orders]),
            ComponentSchedule.status.notin_(["無法進行排程", "模具"]),  # 排除無法排程和模具
            ComponentSchedule.quantity > 0  # 過濾掉數量為0的元件
        )
        
        # 根據 reschedule_all 決定是否包含已排程的
        if not request.reschedule_all:
            query = query.filter(ComponentSchedule.status == "未排程")
        
        component_schedules = query.all()
        
        for schedule in component_schedules:
            # 找到對應的訂單以獲取交期等資訊
            order = next((o for o in orders if o.id == schedule.order_id), None)
            if not order:
                continue
            
            mo = ManufacturingOrder(
                id=str(schedule.id),  # 使用 ComponentSchedule 的 ID
                order_id=str(schedule.order_id),  # 訂單 ID
                component_code=schedule.component_code,  # 子件品號（1字頭）
                product_code=order.product_code,  # 成品品號（0字頭）作為參考
                quantity=schedule.quantity,  # 使用子件數量
                ship_due=datetime.strptime(order.due_date, '%Y-%m-%d') if isinstance(order.due_date, str) else order.due_date,
                priority=order.priority or 2,
                status="PENDING"
            )
            mos.append(mo)
        
        if not mos:
            # 檢查原因
            all_components = db.query(ComponentSchedule).filter(
                ComponentSchedule.order_id.in_([o.id for o in orders])
            ).count()
            
            status_counts = {}
            for status, count in db.query(
                ComponentSchedule.status,
                func.count(ComponentSchedule.id)
            ).filter(
                ComponentSchedule.order_id.in_([o.id for o in orders])
            ).group_by(ComponentSchedule.status).all():
                status_counts[status] = count
            
            if not all_components:
                msg = "訂單尚未展開子件，請先在訂單管理頁面點擊「展開子件」"
            elif request.reschedule_all:
                msg = f"沒有可排程的子件。狀態分佈: {status_counts}"
            else:
                msg = f"沒有「未排程」狀態的子件可排程。狀態分佈: {status_counts}。如需重新排程，請勾選「重新排程所有」選項。"
            
            return SchedulingResponse(
                success=False,
                message=msg,
                blocks=[],
                scheduled_mos=[],
                failed_mos=[],
                total_mos=0,
                on_time_count=0,
                late_count=0,
                total_lateness_days=0,
                changeover_count=0,
                delay_reports=[],
                change_log=[],
                execution_time_seconds=0
            )
        
        # 3. 創建排程引擎配置
        # 找到下一個有工作時數的日期作為排程起點
        now = datetime.now()
        next_work_day = db.query(WorkCalendarDay).filter(
            WorkCalendarDay.work_date >= now.date().isoformat(),
            WorkCalendarDay.work_hours > 0
        ).order_by(WorkCalendarDay.work_date).first()
        
        # 如果找到工作日，設定為該日早上8點；否則使用現在時間
        if next_work_day and next_work_day.work_date > now.date().isoformat():
            # 下一個工作日
            scheduling_start = datetime.strptime(next_work_day.work_date, '%Y-%m-%d').replace(hour=8, minute=0, second=0)
        elif next_work_day and next_work_day.work_date == now.date().isoformat() and next_work_day.work_hours > 0:
            # 今天是工作日，使用現在時間
            scheduling_start = now
        else:
            # 今天非工作日，使用現在時間（引擎會自動調整）
            scheduling_start = now
        
        config = SchedulingConfig(
            now_datetime=scheduling_start,
            merge_enabled=request.merge_enabled,
            merge_window_weeks=request.merge_window_weeks,
            time_threshold_pct=request.time_threshold_pct
        )
        
        # 4. 執行排程
        engine = SchedulingEngine(db, config)
        
        # 獲取現有排程區塊（從 ComponentSchedule）
        existing_schedules = db.query(ComponentSchedule).all()
        existing_blocks = []
        # TODO: 如果需要考慮現有排程，需要將 ComponentSchedule 轉換為 ScheduleBlock
        
        result = engine.schedule(mos, existing_blocks)
        
        # 5. 保存排程結果到資料庫
        # 更新成功排程的 ComponentSchedule
        scheduled_mo_ids = set()
        if result.blocks:
            for block in result.blocks:
                for i, mo_id in enumerate(block.mo_ids):
                    scheduled_mo_ids.add(mo_id)
                    
                    # 找到對應的 ComponentSchedule 記錄並更新
                    schedule = db.query(ComponentSchedule).filter(
                        ComponentSchedule.id == mo_id
                    ).first()
                    
                    if schedule:
                        schedule.machine_id = block.machine_id
                        schedule.scheduled_start_time = block.start_time.isoformat()
                        schedule.scheduled_end_time = block.end_time.isoformat()
                        schedule.scheduled_date = block.start_time.strftime('%Y-%m-%d')
                        schedule.status = "已排程"
                        schedule.updated_at = datetime.utcnow()
            
            # 保存每日分段資訊
            save_daily_schedule_blocks(db, result.blocks)
        
        # 更新失敗排程的 ComponentSchedule
        for mo_id in result.failed_mos:
            if mo_id not in scheduled_mo_ids:
                schedule = db.query(ComponentSchedule).filter(
                    ComponentSchedule.id == mo_id
                ).first()
                
                if schedule:
                    schedule.status = "無法進行排程"
                    schedule.updated_at = datetime.utcnow()
        
        db.commit()
        
        # 6. 轉換為響應格式
        execution_time = time.time() - start_time
        
        return SchedulingResponse(
            success=result.success,
            message=result.message,
            blocks=[
                ScheduleBlockResponse(
                    block_id=b.block_id,
                    machine_id=b.machine_id,
                    mold_code=b.mold_code,
                    start_time=b.start_time.isoformat(),
                    end_time=b.end_time.isoformat(),
                    mo_ids=b.mo_ids,
                    component_codes=b.component_codes,
                    product_display=b.product_display,
                    status=b.status,
                    is_merged=b.is_merged
                )
                for b in result.blocks
            ],
            scheduled_mos=result.scheduled_mos,
            failed_mos=result.failed_mos,
            total_mos=result.total_mos,
            on_time_count=result.on_time_count,
            late_count=result.late_count,
            total_lateness_days=result.total_lateness_days,
            changeover_count=result.changeover_count,
            delay_reports=result.delay_reports,
            change_log=result.change_log,
            execution_time_seconds=round(execution_time, 2)
        )
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"排程錯誤: {error_detail}")
        
        return SchedulingResponse(
            success=False,
            message=f"排程失敗: {str(e)}",
            blocks=[],
            scheduled_mos=[],
            failed_mos=[],
            total_mos=0,
            on_time_count=0,
            late_count=0,
            total_lateness_days=0,
            changeover_count=0,
            delay_reports=[],
            change_log=[],
            execution_time_seconds=time.time() - start_time
        )


@app.get("/api/scheduling/status")
def get_scheduling_status(db: Session = Depends(get_db)):
    """獲取排程狀態"""
    # 統計待排程訂單數
    pending_orders = db.query(Order).filter(Order.status != "已完成").count()
    
    # 統計已排程訂單數
    scheduled_orders = db.query(ComponentSchedule).distinct(ComponentSchedule.order_id).count()
    
    return {
        "pending_orders": pending_orders,
        "scheduled_orders": scheduled_orders,
        "last_schedule_time": None  # TODO: 從 ComponentSchedule 獲取最後排程時間
    }


# 運行服務器
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
