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
import re
import shutil
import json
from datetime import datetime, timedelta
import time

from groq import Groq
from dotenv import load_dotenv

from database import get_db, init_db, Order, Downtime, MachineProductHistory, Machine, Component, BOM, ComponentSchedule, Completion, Product, MoldData, MoldCalculation, WorkCalendarDay, WorkCalendarGap, DailyScheduleBlock, MoldManufacturingOrder, MoldOrderDetail
from schemas import (
    OrderCreate, OrderUpdate, OrderResponse,
    DowntimeCreate, DowntimeResponse,
    MachineProductHistoryResponse,
    MachineResponse,
    ComponentCreate, ComponentResponse,
    BOMCreate, BOMResponse,
    ComponentScheduleResponse,
    OrderDetailResponse,
    CompletionCreate, CompletionResponse,
    ChatRequest, ChatResponse, ChatMessage
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
from mold_mo_generator import MoldMOGenerator

# ==================== 載入環境變數 ====================
load_dotenv()

# ==================== Groq LLM 設定 ====================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client: Optional[Groq] = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
    print("✅ Groq client 初始化完成")
else:
    print("⚠️ 尚未設定 GROQ_API_KEY，Chat 助理將無法呼叫模型")

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
            # 對於合併製令，使用所有子件的組合作為鍵值
            component_display = ','.join(block.component_codes) if len(block.component_codes) > 1 else block.component_codes[0]
            key = (block.mo_ids[0], component_display, block.machine_id)
            block_groups[key].append(block)
    
    # 保存到資料庫並建立前後關聯
    for key, group_blocks in block_groups.items():
        # 按開始時間排序
        group_blocks.sort(key=lambda b: b.start_time)
        order_id, component_display, machine_id = key
        total_sequences = len(group_blocks)
        
        saved_blocks = []
        for seq, block in enumerate(group_blocks, start=1):
            # 使用product_display來顯示合併的子件信息
            display_text = block.product_display if hasattr(block, 'product_display') else component_display
            daily_block = DailyScheduleBlock(
                order_id=order_id,
                component_code=display_text,  # 使用合併後的顯示文字
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
    
    規則：
    1. 子件(1開頭)先完成報完工，成品(0開頭)後完成
    2. 當子件未交數量 > 成品未交數量時，子件未交數量 = 成品未交數量
    3. 當訂單的所有成品未交數量 = 0 時，自動刪除該訂單
    """
    # 判斷是子件還是成品
    is_component = product_code.startswith('1')  # 1開頭是子件
    is_finished = product_code.startswith('0')    # 0開頭是成品
    
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
    orders_to_check = set()  # 需要檢查是否完成的訂單
    
    for product in products:
        if remaining <= 0:
            break
        
        # 計算本次扣除數量
        deduct_qty = min(remaining, product.undelivered_quantity)
        
        # 扣除產品未交數量
        product.undelivered_quantity -= deduct_qty
        print(f"✓ 品號 {product_code} (訂單 {product.order_id[:8]}...) 未交數量: {product.undelivered_quantity + deduct_qty} → {product.undelivered_quantity}")
        
        # 只有成品報完工才同步更新 Order 表
        order = db.query(Order).filter_by(id=product.order_id).first()
        if is_finished and order and order.undelivered_quantity is not None and order.undelivered_quantity > 0:
            order.undelivered_quantity = max(0, order.undelivered_quantity - deduct_qty)
            print(f"  → 同步更新訂單 {order.order_number} 未交數量: {order.undelivered_quantity + deduct_qty} → {order.undelivered_quantity}")
            orders_to_check.add(product.order_id)
        
        # 無論是子件還是成品報完工，都要檢查並調整子件未交數量
        # 查找同訂單的成品和子件
        finished_products = db.query(Product).filter(
            Product.order_id == product.order_id,
            Product.product_type == 'finished'
        ).all()
        
        component_products = db.query(Product).filter(
            Product.order_id == product.order_id,
            Product.product_type == 'component'
        ).all()
        
        # 對每個子件，根據成品未交數量調整子件未交數量
        for finished in finished_products:
            if finished.undelivered_quantity is not None:
                for comp in component_products:
                    if comp.undelivered_quantity is not None:
                        # 1開頭子件：當子件未交 > 成品未交時，調整子件 = 成品
                        # 當子件未交 < 成品時，不動（保持子件的實際狀態）
                        if comp.product_code.startswith('1'):
                            if comp.undelivered_quantity > finished.undelivered_quantity:
                                old_qty = comp.undelivered_quantity
                                comp.undelivered_quantity = finished.undelivered_quantity
                                print(f"  ⚠️ 子件 {comp.product_code} 未交數量({old_qty})超過成品需求({finished.undelivered_quantity})，已調整為{comp.undelivered_quantity}")
                        
                        # 6開頭的模具：回次根據「1開頭子件的最小未交數量」計算
                        # 如果子件都 >= 成品，則用成品計算；如果有子件 < 成品，則用最小子件計算
                        elif comp.product_code.startswith('6'):
                            # 找出所有1開頭子件的未交數量
                            component_undelivered = [c.undelivered_quantity for c in component_products 
                                                    if c.product_code.startswith('1') and c.undelivered_quantity is not None]
                            
                            # 取子件和成品中的最小值作為模具計算基準
                            if component_undelivered:
                                base_qty = min(min(component_undelivered), finished.undelivered_quantity)
                            else:
                                base_qty = finished.undelivered_quantity
                            
                            mold_calc = db.query(MoldCalculation).filter(
                                MoldCalculation.mold_code == comp.product_code
                            ).first()
                            cavity_count = mold_calc.cavity_count if mold_calc and mold_calc.cavity_count else 1
                            expected_qty = math.ceil(base_qty / cavity_count) if base_qty > 0 else 0
                            
                            if comp.undelivered_quantity != expected_qty:
                                old_qty = comp.undelivered_quantity
                                comp.undelivered_quantity = expected_qty
                                print(f"  ⚠️ 模具 {comp.product_code} 回次調整: {old_qty} → {comp.undelivered_quantity} (基準數量:{base_qty}, 穴數:{cavity_count})")

        
        remaining -= deduct_qty
        updated_count += 1
    
    if remaining > 0:
        print(f"⚠️ 警告: 品號 {product_code} 完工數量超過未交數量，剩餘 {remaining} 未扣除")
    
    # 檢查成品報完工後，訂單是否已全部完成
    for order_id in orders_to_check:
        order = db.query(Order).filter_by(id=order_id).first()
        if not order:
            continue
        
        # 查找該訂單的所有成品
        finished_products = db.query(Product).filter(
            Product.order_id == order_id,
            Product.product_type == 'finished'
        ).all()
        
        # 檢查是否所有成品未交數量都為0
        all_finished = all(
            p.undelivered_quantity is not None and p.undelivered_quantity == 0 
            for p in finished_products
        )
        
        if all_finished and len(finished_products) > 0:
            print(f"🎉 訂單 {order.order_number} 所有成品已完成，刪除訂單")
            
            # 刪除訂單相關的所有資料
            # 1. 刪除 Product
            db.query(Product).filter(Product.order_id == order_id).delete()
            # 2. 刪除 ComponentSchedule
            db.query(ComponentSchedule).filter(ComponentSchedule.order_id == order_id).delete()
            # 3. 刪除 DailyScheduleBlock (透過 ComponentSchedule)
            comp_schedule_ids = [cs.id for cs in db.query(ComponentSchedule).filter(ComponentSchedule.order_id == order_id).all()]
            if comp_schedule_ids:
                db.query(DailyScheduleBlock).filter(DailyScheduleBlock.order_id.in_(comp_schedule_ids)).delete(synchronize_session=False)
            # 4. 刪除 Order
            db.delete(order)
    
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

# ==================== 模具機台適配性 API ====================

@app.get("/api/mold/{mold_code}/compatible-machines")
def get_compatible_machines(mold_code: str, db: Session = Depends(get_db)):
    """獲取與指定模具適配的機台列表"""
    compatible_machines = db.query(MoldData.machine_id).filter(
        MoldData.mold_code == mold_code
    ).distinct().all()
    
    machine_ids = [m.machine_id for m in compatible_machines]
    return {"mold_code": mold_code, "compatible_machines": machine_ids}

@app.get("/api/mold/check-compatibility/{mold_code}/{machine_id}")
def check_mold_machine_compatibility(mold_code: str, machine_id: str, db: Session = Depends(get_db)):
    """檢查模具與機台的適配性"""
    print(f"🔍 檢查適配性: 模具={mold_code}, 機台={machine_id}")
    
    compatible = db.query(MoldData).filter(
        MoldData.mold_code == mold_code,
        MoldData.machine_id == machine_id
    ).first()
    
    result = compatible is not None
    print(f"✅ 適配性結果: {result}")
    
    return {
        "mold_code": mold_code, 
        "machine_id": machine_id, 
        "compatible": result
    }

# ==================== 報完工 API ====================

def update_schedule_after_completion(db: Session, product_code: str, completed_qty: int):
    """
    報完工後更新排程甘特圖
    邏輯：固定end time，調整start time（時間縮短）
    """
    # 查找該產品相關的DailyScheduleBlock
    blocks = db.query(DailyScheduleBlock).join(
        Order, DailyScheduleBlock.order_id == Order.id
    ).filter(
        Order.product_code == product_code,
        DailyScheduleBlock.status == "已排程"
    ).order_by(DailyScheduleBlock.sequence).all()
    
    if not blocks:
        print(f"⚠️ 未找到品號 {product_code} 的排程區塊")
        return
    
    # 計算完工比例
    first_block_order = db.query(Order).filter(Order.id == blocks[0].order_id).first()
    if not first_block_order or not first_block_order.quantity or first_block_order.quantity == 0:
        print(f"⚠️ 無法計算完工比例：訂單數量為 {first_block_order.quantity if first_block_order else 'None'}")
        return
    
    completion_ratio = completed_qty / first_block_order.quantity
    print(f"🔄 品號 {product_code} 完工比例: {completed_qty}/{first_block_order.quantity} = {completion_ratio:.2%}")
    
    # 對每個區塊進行調整
    updated_count = 0
    for block in blocks:
        original_duration = (block.end_time - block.start_time).total_seconds()
        # 計算新的持續時間（減去已完工的比例）
        new_duration_seconds = original_duration * (1 - completion_ratio)
        
        if new_duration_seconds <= 0:
            # 如果完工量太大，直接刪除該區塊
            print(f"  🗑️ 刪除區塊 {block.id[:8]}... (已完全完工)")
            db.delete(block)
        else:
            # 固定end time，調整start time
            original_end_time = block.end_time
            new_start_time = original_end_time - timedelta(seconds=new_duration_seconds)
            
            print(f"  📏 調整區塊 {block.id[:8]}...")
            print(f"    原始: {block.start_time.strftime('%H:%M')} - {block.end_time.strftime('%H:%M')} ({original_duration/3600:.2f}h)")
            print(f"    新的: {new_start_time.strftime('%H:%M')} - {original_end_time.strftime('%H:%M')} ({new_duration_seconds/3600:.2f}h)")
            
            block.start_time = new_start_time
            updated_count += 1
    
    print(f"✅ 更新了 {updated_count} 個排程區塊")

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
    
    # 更新排程甘特圖（固定end time，調整start time）
    update_schedule_after_completion(db, data.finished_item_no, data.completed_qty)
    
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
        # 檢查完工單號是否已存在
        exists = db.query(Completion).filter(
            Completion.completion_no == payload.completion_no
        ).first()
        if exists:
            skipped += 1
            skipped_nos.append(payload.completion_no)
            continue
        
        # 新增報完工記錄
        row = Completion(**payload.model_dump())
        db.add(row)
        
        # 更新對應產品的未交數量
        update_undelivered_quantity(db, payload.finished_item_no, payload.completed_qty)
        
        # 更新排程甘特圖（固定end time，調整start time）
        update_schedule_after_completion(db, payload.finished_item_no, payload.completed_qty)
        
        # 立即提交這筆記錄，避免因後續錯誤而回滾
        db.commit()
        inserted += 1
    
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
                    # 查找對應的 Product 以獲取 undelivered_quantity
                    product_record = db.query(Product).filter(
                        Product.order_id == order.id,
                        Product.product_code == bom_item.component_code
                    ).first()
                    
                    # 使用 undelivered_quantity（未交數量）而不是 quantity
                    display_quantity = product_record.undelivered_quantity if product_record and product_record.undelivered_quantity is not None else comp_schedule.quantity
                    
                    components_list.append({
                        "component_code": comp_schedule.component_code,
                        "quantity": display_quantity,
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
    
    # 重新生成該日期的工作日曆間隙
    regenerate_work_calendar_gaps(db, [{"work_date": work_date}])
    
    return {
        "message": "Work calendar day saved successfully"
    }

@app.post("/api/work-calendar/batch")
def batch_upsert_work_calendar(
    data: dict,
    db: Session = Depends(get_db)
):
    """批量新增或更新工作日曆"""
    
    days = data.get("days", [])
    
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
    
    # 重新生成影響日期的工作日曆間隙
    regenerate_work_calendar_gaps(db, days)
    
    return {
        "message": f"Batch saved {len(days)} work calendar days"
    }


def regenerate_work_calendar_gaps(db: Session, days_data):
    """根據 WorkCalendarDay 重新生成 WorkCalendarGap 記錄"""
    from datetime import datetime, time, timedelta
    
    # 收集需要重新生成的日期
    affected_dates = set()
    for day_data in days_data:
        work_date = day_data.get("work_date")
        if work_date:
            affected_dates.add(work_date)
    
    for work_date_str in affected_dates:
        # 刪除該日期的舊間隙記錄
        db.query(WorkCalendarGap).filter(
            WorkCalendarGap.work_date == work_date_str
        ).delete()
        
        # 查詢該日期的工作時間設定
        work_day = db.query(WorkCalendarDay).filter(
            WorkCalendarDay.work_date == work_date_str
        ).first()
        
        if not work_day or work_day.work_hours <= 0:
            continue
            
        # 解析開始時間
        try:
            start_hour, start_minute = map(int, work_day.start_time.split(':'))
        except:
            start_hour, start_minute = 8, 0  # 預設 08:00
            
        # 計算工作時間區間（需要考慮休息時間）
        work_date = datetime.strptime(work_date_str, '%Y-%m-%d').date()
        start_datetime = datetime.combine(work_date, time(start_hour, start_minute))
        
        # 計算總時間（工作時間 + 1小時休息時間）
        total_hours = work_day.work_hours + 1
        end_datetime = start_datetime + timedelta(hours=total_hours)
        
        # 不分段，直接創建單一間隙（即使跨日）
        gap = WorkCalendarGap(
            work_date=work_date_str,
            gap_start=start_datetime,
            gap_end=end_datetime,
            duration_hours=total_hours
        )
        db.add(gap)
    
    db.commit()


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
        
        # 獲取模具編號（從MoldData查找）
        mold_data = db.query(MoldData).filter(
            MoldData.component_code == block.component_code
        ).first()
        mold_code = mold_data.mold_code if mold_data else None
        
        if block.sequence == 1:  # 只在第一個區塊打印，避免過多日誌
            print(f"📦 區塊 {block.order_id[:8]}: 子件={block.component_code}, 模具={mold_code}")
        
        result.append({
            "id": f"{block.order_id}-{block.sequence}",
            "orderId": order_number,  # 顯示訂單編號而不是 UUID
            "originalOrderId": block.order_id,  # 保留原始 order_id 供更新使用
            "productId": block.component_code,
            "moldCode": mold_code,  # 新增模具編號
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
    批量更新排程區塊
    - 接收前端拖動後的排程更新
    - 按 orderId 分組處理「時間鏈」
    - 拖動任一段時：
      1. 所有區塊的 machine_id 同步
      2. 被拖動段採用新時間
      3. 後續段全部順延（接在前一段後）
    """

    from datetime import datetime, timedelta
    from collections import defaultdict

    print(f"\n=== 收到批量更新請求 ===")
    print(f"更新數量: {len(request.updates)}")
    print(f"刪除 ID 數量: {len(request.deletedIds)}")
    
    updated_count = 0
    errors = []

    try:
        # 按 orderId 分組處理
        grouped = defaultdict(list)
        for u in request.updates:
            grouped[u.orderId].append(u)
        
        print(f"分組數: {len(grouped)}")

        for order_id, updates in grouped.items():
            print(f"\n處理訂單: {order_id}, 區塊數: {len(updates)}")

            # 1️⃣ 找到被修改的錨點區塊
            anchor = next((u for u in updates if getattr(u, "isModified", False)), None)
            if not anchor:
                print(f"  ⚠️ 訂單 {order_id} 沒有錨點區塊，跳過")
                continue

            target_machine = anchor.machineId
            print(f"  錨點: {anchor.id}, 目標機台: {target_machine}")

            # 2️⃣ 從資料庫撈取該訂單的所有區塊（依 sequence 排序）
            blocks = db.query(DailyScheduleBlock).filter(
                DailyScheduleBlock.order_id == order_id
            ).order_by(DailyScheduleBlock.sequence).all()

            if not blocks:
                print(f"  ⚠️ 資料庫中找不到訂單 {order_id} 的區塊")
                errors.append(f"訂單 {order_id} 不存在於資料庫")
                continue

            print(f"  資料庫區塊數: {len(blocks)}")

            # 3️⃣ 統一所有區塊的 machine_id
            for b in blocks:
                if b.machine_id != target_machine:
                    print(f"    更新區塊 {b.id} 機台: {b.machine_id} -> {target_machine}")
                b.machine_id = target_machine

            # 4️⃣ 找到錨點對應的資料庫區塊
            # 嘗試多種 ID 格式匹配：
            # 1. {order_id}-{sequence} (資料庫格式)
            # 2. 直接用前端的 id 去匹配 block.id (可能是 split-xxx 或 order_id-sequence)
            anchor_block = None
            
            # 方法1: 標準格式匹配 {order_id}-{sequence}
            for b in blocks:
                if f"{b.order_id}-{b.sequence}" == anchor.id:
                    anchor_block = b
                    break
            
            # 方法2: 如果沒找到，檢查是否是 originalId 格式
            if not anchor_block and hasattr(anchor, 'originalId') and anchor.originalId:
                for b in blocks:
                    if f"{b.order_id}-{b.sequence}" == anchor.originalId:
                        anchor_block = b
                        break
            
            # 方法3: 如果還是沒找到，嘗試解析 anchor.id 取 sequence
            if not anchor_block:
                # 嘗試從 ID 中提取 sequence (例如: split-123-1 -> sequence=1)
                import re
                match = re.search(r'-(\d+)$', anchor.id)
                if match:
                    try:
                        seq = int(match.group(1))
                        if seq <= len(blocks):
                            anchor_block = blocks[seq - 1]  # sequence 是 1-based
                            print(f"  通過 sequence 推斷找到錨點: sequence={seq}")
                    except (ValueError, IndexError):
                        pass
            
            if not anchor_block:
                print(f"  ⚠️ 找不到錨點區塊 {anchor.id}")
                errors.append(f"錨點區塊 {anchor.id} 不存在")
                continue

            print(f"  找到錨點區塊: sequence={anchor_block.sequence}")

            # 5️⃣ 將前端的 hour 格式轉換為 datetime
            base_date = datetime.strptime(anchor.scheduledDate, "%Y-%m-%d")

            def hour_to_dt(hour):
                d = int(hour // 24)
                h = int(hour % 24)
                m = int((hour * 60) % 60)
                return base_date + timedelta(days=d, hours=h, minutes=m)

            new_start = hour_to_dt(anchor.startHour)
            new_end = hour_to_dt(anchor.endHour)

            print(f"  更新錨點時間: {anchor_block.start_time} -> {new_start}")
            print(f"                {anchor_block.end_time} -> {new_end}")

            # 計算錨點區塊（第一段）的時長變化（在更新前）
            old_anchor_duration = (anchor_block.end_time - anchor_block.start_time).total_seconds()
            new_anchor_duration = (new_end - new_start).total_seconds()
            anchor_duration_change = new_anchor_duration - old_anchor_duration
            
            print(f"  第一段時長變化: {old_anchor_duration/3600:.2f}h -> {new_anchor_duration/3600:.2f}h (變化: {anchor_duration_change/3600:.2f}h)")

            # 更新錨點區塊的時間
            anchor_block.start_time = new_start
            anchor_block.end_time = new_end

            # 6️⃣ 後續區塊「接龍順延」或「按總時長重新分配」
            
            prev = anchor_block
            for b in blocks:
                if b.sequence <= anchor_block.sequence:
                    continue

                old_start = b.start_time
                old_end = b.end_time
                old_duration = (old_end - old_start).total_seconds()
                
                # 如果是最後一段，且第一段時長有變化，則調整最後一段的時長（總時長不變）
                if b.sequence == len(blocks) and anchor_duration_change != 0 and anchor_block.sequence == 1:
                    # 最後一段的新時長 = 原時長 - 第一段的時長變化（反向補償）
                    new_duration_seconds = old_duration - anchor_duration_change
                    
                    # 確保最後一段至少有 0.1 小時（6 分鐘）
                    if new_duration_seconds < 360:  # 360 秒 = 6 分鐘
                        new_duration_seconds = 360
                    
                    # 檢查前一區塊的結束時間
                    prev_end_hour = prev.end_time.hour + (prev.end_time.minute / 60.0)
                    if prev_end_hour < 8:
                        # 前一區塊結束在凌晨，從同一天的 8:00 開始
                        b.start_time = prev.end_time.replace(hour=8, minute=0, second=0, microsecond=0)
                    else:
                        b.start_time = prev.end_time
                    
                    b.end_time = b.start_time + timedelta(seconds=new_duration_seconds)
                    print(f"  調整最後段 {b.sequence}: 時長 {old_duration/3600:.2f}h -> {new_duration_seconds/3600:.2f}h (補償第一段變化)")
                else:
                    # 中間段：保持原時長，順延時間
                    duration = b.end_time - b.start_time
                    
                    # 檢查工作時間邊界
                    prev_end_hour = prev.end_time.hour + (prev.end_time.minute / 60.0)
                    if prev_end_hour < 8:
                        b.start_time = prev.end_time.replace(hour=8, minute=0, second=0, microsecond=0)
                    else:
                        b.start_time = prev.end_time
                    
                    b.end_time = b.start_time + duration
                    print(f"  順延區塊 {b.sequence}: {old_start} -> {b.start_time}")
                
                prev = b

            # 7️⃣ 修正 scheduled_date（08:00 規則）
            for b in blocks:
                old_date = b.scheduled_date
                if b.start_time.hour < 8:
                    b.scheduled_date = (b.start_time.date() - timedelta(days=1)).isoformat()
                else:
                    b.scheduled_date = b.start_time.date().isoformat()
                
                if old_date != b.scheduled_date:
                    print(f"  調整日期 {b.sequence}: {old_date} -> {b.scheduled_date}")

            updated_count += len(blocks)

        db.commit()
        print(f"\n✅ 批量更新成功，共更新 {updated_count} 個區塊")

        return {
            "success": True,
            "updated_count": updated_count,
            "errors": errors
        }

    except Exception as e:
        db.rollback()
        error_msg = f"批量更新失敗: {str(e)}"
        print(f"\n❌ {error_msg}")
        import traceback
        traceback.print_exc()
        
        return {
            "success": False,
            "updated_count": 0,
            "errors": [error_msg]
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
                execution_time_seconds=0,
                ai_summary=None
            )
        
        # 2. 使用模具製令生成器創建以模具為單位的製令
        print(f"\n=== 開始生成模具製令（訂單數: {len(orders)}）===")
        
        mold_generator = MoldMOGenerator(db)
        
        # 清空舊的模具製令（如果需要重新排程）
        if request.reschedule_all:
            print("清空舊的模具製令...")
            mold_generator.clear_mold_mos()
        
        # 生成模具製令
        order_ids = [o.id for o in orders]
        mold_mos = mold_generator.generate_mold_mos(order_ids)
        
        if not mold_mos:
            msg = "無法生成模具製令，請檢查訂單是否已展開子件並有對應的模具資料"
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
                execution_time_seconds=0,
                ai_summary=None
            )
        
        # 將模具製令轉換為排程引擎的 ManufacturingOrder 格式
        mos = []
        mold_mo_mapping = {}  # 映射: mo.id -> mold_mo
        
        for mold_mo in mold_mos:
            # 模具製令的 component_code 可能包含多個子件（逗號分隔）
            # 取第一個子件來查詢模具資料
            first_component = mold_mo.component_code.split(',')[0] if ',' in mold_mo.component_code else mold_mo.component_code
            
            # 查詢模具資料以獲取平均成型時間等信息
            mold_data = db.query(MoldData).filter(
                MoldData.mold_code == mold_mo.mold_code
            ).first()  # 只用模具編號查詢
            
            # 創建製令（以模具為單位）
            mo = ManufacturingOrder(
                id=mold_mo.id,  # 使用模具製令的 ID
                order_id=mold_mo.id,  # 模具製令本身就是一個訂單單位
                component_code=mold_mo.component_code,  # 使用完整的子件列表（逗號分隔）
                product_code=first_component,  # 使用第一個子件作為產品代碼
                quantity=mold_mo.total_rounds,  # 使用總回次作為數量（排程引擎需要）
                ship_due=datetime.strptime(mold_mo.earliest_due_date, '%Y-%m-%d') if isinstance(mold_mo.earliest_due_date, str) else mold_mo.earliest_due_date,
                priority=mold_mo.highest_priority,
                status="PENDING"
            )
            mos.append(mo)
            mold_mo_mapping[mo.id] = mold_mo
            
            print(f"模具製令: {mold_mo.mold_code} → 子件: {mold_mo.component_code}, 回次: {mold_mo.total_rounds}, 交期: {mold_mo.earliest_due_date}")
        
        print(f"共生成 {len(mos)} 個模具製令\n")
        
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
        
        # 4. 執行排程（根據模式選擇）
        engine = SchedulingEngine(db, config)
        
        # 獲取現有排程區塊（從 ComponentSchedule）
        existing_schedules = db.query(ComponentSchedule).all()
        existing_blocks = []
        # TODO: 如果需要考慮現有排程，需要將 ComponentSchedule 轉換為 ScheduleBlock
        
        # 根據排程模式選擇不同的排程策略
        if request.scheduling_mode == 'fill_all_machines':
            print("🎯 執行填滿機台模式排程...")
            result = engine.schedule_fill_all_machines(mos, existing_blocks)
        else:
            print("📋 執行標準模式排程...")
            result = engine.schedule(mos, existing_blocks)
        
        # 5. 保存排程結果到資料庫
        # 更新模具製令的排程信息
        scheduled_mo_ids = set()
        if result.blocks:
            for block in result.blocks:
                for i, mo_id in enumerate(block.mo_ids):
                    scheduled_mo_ids.add(mo_id)
                    
                    # 更新模具製令的排程信息
                    mold_mo = db.query(MoldManufacturingOrder).filter(
                        MoldManufacturingOrder.id == mo_id
                    ).first()
                    
                    if mold_mo:
                        mold_mo.scheduled_machine = block.machine_id
                        mold_mo.scheduled_start = block.start_time
                        mold_mo.scheduled_end = block.end_time
                        mold_mo.status = "已排程"
                        mold_mo.updated_at = datetime.utcnow()
                        
                        # 同時更新關聯的 ComponentSchedule（如果存在）
                        # 查找該模具製令包含的訂單
                        details = db.query(MoldOrderDetail).filter(
                            MoldOrderDetail.mold_mo_id == mo_id
                        ).all()
                        
                        for detail in details:
                            # 更新對應的 ComponentSchedule（需要匹配訂單和子件）
                            schedule = db.query(ComponentSchedule).filter(
                                ComponentSchedule.order_id == detail.order_id,
                                ComponentSchedule.component_code == detail.component_code  # 使用明細中的具體子件
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
        
        # 更新失敗排程的模具製令
        for mo_id in result.failed_mos:
            if mo_id not in scheduled_mo_ids:
                mold_mo = db.query(MoldManufacturingOrder).filter(
                    MoldManufacturingOrder.id == mo_id
                ).first()
                
                if mold_mo:
                    mold_mo.status = "無法排程"
                    mold_mo.updated_at = datetime.utcnow()
                    
                    # 同時更新關聯的 ComponentSchedule
                    details = db.query(MoldOrderDetail).filter(
                        MoldOrderDetail.mold_mo_id == mo_id
                    ).all()
                    
                    for detail in details:
                        schedule = db.query(ComponentSchedule).filter(
                            ComponentSchedule.order_id == detail.order_id,
                            ComponentSchedule.component_code == detail.component_code  # 使用明細中的具體子件
                        ).first()
                        
                        if schedule:
                            schedule.status = "無法進行排程"
                            schedule.updated_at = datetime.utcnow()
        
        db.commit()
        
        # 6. 生成 AI 排程總結
        print(f"\n=== 生成排程總結報告 ===")
        ai_summary = generate_scheduling_summary(
            db=db,
            result=result,
            scheduled_mo_ids=scheduled_mo_ids,
            failed_mo_ids=set(result.failed_mos)
        )
        
        # 7. 轉換為響應格式
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
            execution_time_seconds=round(execution_time, 2),
            ai_summary=ai_summary
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
            execution_time_seconds=time.time() - start_time,
            ai_summary=None
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


# ==================== 排程報告生成 ====================

def generate_scheduling_summary(
    db: Session,
    result,  # SchedulingResult from scheduling engine
    scheduled_mo_ids: set,
    failed_mo_ids: set
):
    """
    使用 LLM 生成排程結果的自然語言總結
    
    包含：
    1. 延遲訂單數
    2. 未排程訂單 & 原因
    3. 排程成功數
    4. 機台使用率（當月份）
    """
    if not groq_client:
        return None
    
    try:
        # 1. 統計延遲訂單（交期早於今天且未完成）
        today = datetime.now().strftime("%Y-%m-%d")
        delayed_orders = db.query(Order).filter(
            Order.due_date < today,
            Order.status != "已完成",
            Order.status != "COMPLETED"
        ).count()
        
        # 2. 統計未排程訂單及原因
        unscheduled_orders = []
        if failed_mo_ids:
            for mo_id in failed_mo_ids:
                mold_mo = db.query(MoldManufacturingOrder).filter(
                    MoldManufacturingOrder.id == mo_id
                ).first()
                if mold_mo:
                    # 查詢相關訂單
                    details = db.query(MoldOrderDetail).filter(
                        MoldOrderDetail.mold_mo_id == mo_id
                    ).all()
                    for detail in details:
                        order = db.query(Order).filter(Order.id == detail.order_id).first()
                        if order:
                            unscheduled_orders.append({
                                "order_number": order.order_number,
                                "customer_name": order.customer_name,
                                "mold_code": mold_mo.mold_code,
                                "reason": "排程失敗或無可用機台"
                            })
        
        # 3. 統計排程成功數
        scheduled_count = len(scheduled_mo_ids)
        
        # 4. 計算當月機台使用率
        now = datetime.now()
        month_start = now.replace(day=1).strftime("%Y-%m-%d")
        month_end = (now.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        month_end_str = month_end.strftime("%Y-%m-%d")
        
        print(f"[generate_scheduling_summary] 計算機台使用率: {month_start} ~ {month_end_str}")
        
        all_machines = db.query(Machine).all()
        machine_utilization = {}
        
        # 先計算本月工作日總時數（所有機台共用）
        work_days = db.query(WorkCalendarDay).filter(
            WorkCalendarDay.work_date >= month_start,
            WorkCalendarDay.work_date <= month_end_str,
            WorkCalendarDay.work_hours > 0
        ).all()
        
        total_available_hours = sum(day.work_hours for day in work_days)
        print(f"[generate_scheduling_summary] 本月工作日總時數: {total_available_hours} 小時")
        
        for machine in all_machines:
            # 計算該機台在本月的排程時數
            schedules = db.query(DailyScheduleBlock).filter(
                DailyScheduleBlock.machine_id == machine.machine_id,
                DailyScheduleBlock.scheduled_date >= month_start,
                DailyScheduleBlock.scheduled_date <= month_end_str
            ).all()
            
            total_scheduled_hours = 0
            for schedule in schedules:
                if schedule.start_time and schedule.end_time:
                    # 處理 start_time 和 end_time 可能是 datetime 或 time 類型
                    if isinstance(schedule.start_time, datetime):
                        start_time = schedule.start_time.time()
                    else:
                        start_time = schedule.start_time
                    
                    if isinstance(schedule.end_time, datetime):
                        end_time = schedule.end_time.time()
                    else:
                        end_time = schedule.end_time
                    
                    start = datetime.combine(datetime.today(), start_time)
                    end = datetime.combine(datetime.today(), end_time)
                    hours = (end - start).total_seconds() / 3600
                    total_scheduled_hours += hours
            
            utilization_rate = (total_scheduled_hours / total_available_hours * 100) if total_available_hours > 0 else 0
            machine_utilization[machine.machine_id] = round(utilization_rate, 1)
            print(f"[generate_scheduling_summary] {machine.machine_id}: {total_scheduled_hours}h / {total_available_hours}h = {utilization_rate:.1f}%")
        
        # 計算平均機台使用率
        avg_utilization = round(sum(machine_utilization.values()) / len(machine_utilization), 1) if machine_utilization else 0
        print(f"[generate_scheduling_summary] 平均機台使用率: {avg_utilization}%")
        
        # 構建 LLM 提示
        prompt = f"""請根據以下排程結果數據，生成一份專業的排程總結報告（使用繁體中文）：

【排程執行結果】
- 排程成功的模具製令數：{scheduled_count} 筆
- 排程失敗的模具製令數：{len(failed_mo_ids)} 筆
- 準時製令數：{result.on_time_count} 筆
- 延遲製令數：{result.late_count} 筆
- 總延遲天數：{result.total_lateness_days} 天

【延遲訂單統計】
- 目前系統中延遲訂單（交期已過且未完成）：{delayed_orders} 筆

【未排程訂單】
{f"共 {len(unscheduled_orders)} 筆訂單未能排程：" if unscheduled_orders else "所有訂單皆已成功排程"}
{chr(10).join([f"- 訂單 {o['order_number']} ({o['customer_name']})：模具 {o['mold_code']} - {o['reason']}" for o in unscheduled_orders[:5]])}
{"..." if len(unscheduled_orders) > 5 else ""}

【本月機台使用率】
平均使用率：{avg_utilization}%
{chr(10).join([f"- {machine_id}: {rate}%" for machine_id, rate in sorted(machine_utilization.items())])}

【排程變更】
- 換模次數：{result.changeover_count} 次

請以專業、易懂的方式總結這次排程結果，並提供以下內容：
1. 整體排程狀況評估（成功率、效率）
2. 需要注意的問題（延遲訂單、未排程訂單、低使用率機台）
3. 改善建議（如何提升排程效率或解決問題）

請保持簡潔，總結不超過300字。"""

        print(f"[generate_scheduling_summary] 開始生成 AI 排程總結...")
        print(f"[generate_scheduling_summary] 統計數據 - 成功:{scheduled_count}, 失敗:{len(failed_mo_ids)}, 延遲訂單:{delayed_orders}")
        print(f"[generate_scheduling_summary] Groq client 狀態: {'已初始化' if groq_client else '未初始化'}")
        
        if not groq_client:
            print(f"[generate_scheduling_summary] 錯誤: Groq client 未初始化，無法生成 AI 分析")
            return "Groq API 未配置，無法生成 AI 分析"
        
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "你是一個專業的生產排程分析師，擅長解讀排程數據並提供決策建議。使用繁體中文回答。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        summary = response.choices[0].message.content
        print(f"[generate_scheduling_summary] AI 總結生成完成")
        
        return summary
        
    except Exception as e:
        print(f"[generate_scheduling_summary] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return f"生成 AI 分析時發生錯誤: {str(e)}"


# ==================== Chat 助理工具函數（用於 Function Calling） ====================

def get_orders_summary(db: Session, status: Optional[str] = None, limit: int = 10):
    """查詢訂單摘要"""
    query = db.query(Order)
    if status:
        query = query.filter(Order.status == status)
    orders = query.limit(limit).all()
    
    result = []
    for order in orders:
        result.append({
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "product_code": order.product_code,
            "quantity": order.quantity,
            "due_date": order.due_date,
            "status": getattr(order.status, "value", order.status) if hasattr(order.status, "value") else order.status,
            "priority": order.priority
        })
    
    summary = {
        "total_count": len(result),
        "filter_status": status,
        "limit": limit,
        "orders": result
    }
    print(f"[get_orders_summary] 狀態篩選: {status}, 返回 {len(result)} 筆訂單")
    return summary

def get_order_statistics(db: Session):
    """統計訂單狀態分布"""
    from sqlalchemy import func
    total = db.query(Order).count()
    by_status = db.query(
        Order.status,
        func.count(Order.id)
    ).group_by(Order.status).all()
    
    result = {
        "total_orders": total,
        "by_status": {str(status): count for status, count in by_status}
    }
    print(f"[get_order_statistics] 總訂單數: {total}, 狀態分布: {result['by_status']}")
    return result

def get_machine_schedule(db: Session, machine_id: Optional[str] = None, date: Optional[str] = None):
    """查詢機台排程"""
    query = db.query(DailyScheduleBlock)
    if machine_id:
        query = query.filter(DailyScheduleBlock.machine_id == machine_id)
    if date:
        query = query.filter(DailyScheduleBlock.scheduled_date == date)
    
    schedules = query.all()
    result = []
    for schedule in schedules:
        result.append({
            "machine_id": schedule.machine_id,
            "order_id": schedule.order_id,
            "component_code": schedule.component_code,
            "scheduled_date": schedule.scheduled_date,
            "start_time": schedule.start_time.isoformat() if schedule.start_time else None,
            "end_time": schedule.end_time.isoformat() if schedule.end_time else None,
            "status": schedule.status
        })
    return result

def get_delayed_orders(db: Session):
    """查詢延遲訂單（交期早於今天且未完成的訂單）"""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    delayed = db.query(Order).filter(
        Order.due_date < today,
        Order.status != "已完成",
        Order.status != "COMPLETED"
    ).all()
    
    result = []
    for order in delayed:
        result.append({
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "product_code": order.product_code,
            "due_date": order.due_date,
            "status": getattr(order.status, "value", order.status) if hasattr(order.status, "value") else order.status,
            "priority": order.priority
        })
    
    # 加入查詢摘要，確保 LLM 理解數據
    summary = {
        "total_count": len(result),
        "query_date": today,
        "orders": result
    }
    
    print(f"[get_delayed_orders] 查詢日期: {today}, 找到 {len(result)} 筆延遲訂單")
    return summary

def get_machine_utilization(db: Session, date: Optional[str] = None):
    """統計機台使用率"""
    from sqlalchemy import func
    from datetime import datetime, timedelta
    
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    # 查詢所有機台
    all_machines = db.query(Machine).all()
    
    # 查詢該日期的排程
    schedules = db.query(
        DailyScheduleBlock.machine_id,
        func.count(DailyScheduleBlock.id).label('schedule_count')
    ).filter(
        DailyScheduleBlock.scheduled_date == date
    ).group_by(DailyScheduleBlock.machine_id).all()
    
    schedule_dict = {machine_id: count for machine_id, count in schedules}
    
    result = []
    for machine in all_machines:
        count = schedule_dict.get(machine.machine_id, 0)
        result.append({
            "machine_id": machine.machine_id,
            "area": machine.area,
            "schedule_count": count,
            "status": "使用中" if count > 0 else "閒置"
        })
    
    return result

def get_mold_info(db: Session, mold_code: str):
    """查詢模具資訊"""
    mold_data = db.query(MoldData).filter(MoldData.mold_code == mold_code).all()
    
    if not mold_data:
        return {"error": f"找不到模具 {mold_code}"}
    
    result = {
        "mold_code": mold_code,
        "products": [],
        "compatible_machines": set()
    }
    
    for data in mold_data:
        result["products"].append({
            "product_code": data.product_code,
            "component_code": data.component_code,
            "cavity_count": data.cavity_count,
            "avg_molding_time": data.avg_molding_time
        })
        if data.machine_id:
            result["compatible_machines"].add(data.machine_id)
    
    result["compatible_machines"] = list(result["compatible_machines"])
    return result

def get_completion_summary(db: Session, date: Optional[str] = None, limit: int = 10):
    """查詢完工記錄"""
    query = db.query(Completion)
    if date:
        query = query.filter(Completion.completion_date == date)
    
    completions = query.order_by(Completion.completion_date.desc()).limit(limit).all()
    
    result = []
    for comp in completions:
        result.append({
            "completion_no": comp.completion_no,
            "completion_date": comp.completion_date,
            "finished_item_no": comp.finished_item_no,
            "completed_qty": comp.completed_qty,
            "machine_code": comp.machine_code,
            "mold_code": comp.mold_code
        })
    return result

# 定義可用的工具（Groq Function Calling）
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_orders_summary",
            "description": "查詢訂單列表和摘要資訊，可按狀態篩選",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "訂單狀態，如：PENDING（待處理）、SCHEDULED（已排程）、IN_PROGRESS（生產中）、COMPLETED（已完成）",
                        "enum": ["PENDING", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回的訂單數量上限，預設10筆",
                        "default": 10
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_statistics",
            "description": "統計訂單總數和各狀態的分布情況",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_machine_schedule",
            "description": "查詢機台的排程資訊，可指定機台和日期",
            "parameters": {
                "type": "object",
                "properties": {
                    "machine_id": {
                        "type": "string",
                        "description": "機台編號，如：M01、M02等"
                    },
                    "date": {
                        "type": "string",
                        "description": "日期，格式：YYYY-MM-DD"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_delayed_orders",
            "description": "查詢所有延遲未完成的訂單",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_machine_utilization",
            "description": "統計機台使用率和狀態",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期，格式：YYYY-MM-DD，不提供則查詢今天"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_mold_info",
            "description": "查詢模具的詳細資訊，包含可生產的產品和適配機台",
            "parameters": {
                "type": "object",
                "properties": {
                    "mold_code": {
                        "type": "string",
                        "description": "模具編號，如：6F520009A"
                    }
                },
                "required": ["mold_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_completion_summary",
            "description": "查詢完工記錄",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期，格式：YYYY-MM-DD"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回的記錄數量上限，預設10筆",
                        "default": 10
                    }
                }
            }
        }
    }
]


# ==================== Chat 助理 API（★ 已改版：會真的查 DB） ====================
@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    """
    EPS 智能助理：
    請使用繁體中文回答
    1. 先從問題裡找「訂單編號」或「產品品號」：
       - 訂單編號：連續 8 位以上的數字 → 對應 Order.order_number
       - 產品品號：連續 5 位以上的英數字/減號 → 對應 Order.product_code

    2. 如果查到資料，就直接用資料庫內容回覆（不經過 LLM）。

    3. 如果查不到，再交給 LLM 做一般說明 / 教學。
    """
    q = (req.question or "").strip()

    if not q:
        return ChatResponse(
            answer="請先輸入想查詢的內容，例如「幫我查訂單編號 20240401001 的狀態」。",
            model="system",
        )

    # ★ Debug：印出目前 DB 內的訂單總數，讓你在後端終端機確認真的有連到 DB
    total_orders = db.query(Order).count()
    print(f"[chat] DB 中目前有 {total_orders} 筆 orders")

    # --------------------------------------------------
    # 1️⃣ 嘗試抓「訂單編號」（連續 8 位以上的數字）→ Order.order_number
    # --------------------------------------------------
    order_match = re.search(r"\b\d{8,}\b", q)
    if order_match:
        order_no = order_match.group(0)
        print(f"[chat] 偵測到訂單編號: {order_no}")

        order = db.query(Order).filter(Order.order_number == order_no).first()

        if order:
            # due_date 可能是字串，也可能是 datetime，所以做個防呆
            raw_due = getattr(order, "due_date", None)
            if isinstance(raw_due, str):
                due_date = raw_due
            elif raw_due is not None:
                due_date = raw_due.strftime("%Y/%m/%d")
            else:
                due_date = "未設定"

            undelivered = getattr(order, "undelivered_quantity", None) or 0
            status_value = getattr(order, "status", None)
            # status 可能是 Enum 或 str
            status = getattr(status_value, "value", status_value) or "未設定"

            answer = (
                f"已為你查詢到訂單編號 {order_no}：\n"
                f"- 客戶名稱：{order.customer_name or '（未填寫）'}\n"
                f"- 產品品號：{order.product_code or '（未填寫）'}\n"
                f"- 訂單數量：{order.quantity}\n"
                f"- 未交數量：{undelivered}\n"
                f"- 交期：{due_date}\n"
                f"- 狀態：{status}"
            )

            return ChatResponse(answer=answer, model="db_lookup(order_number)")

        # 找不到這個訂單編號
        return ChatResponse(
            answer=(
                f"系統查不到訂單編號「{order_no}」。\n"
                f"請確認編號是否正確，或改用自然語言提問，例如：\n"
                f"「幫我查訂單 {order_no} 的交期跟剩餘未交數量」"
            ),
            model="db_lookup(order_number)",
        )

    # --------------------------------------------------
    # 2️⃣ 沒有偵測到訂單編號，就嘗試抓「產品品號」→ Order.product_code
    #    規則：連續 5 位以上的英數字或減號（你可以之後依你家的料號再微調）
    # --------------------------------------------------
    product_match = re.search(r"\b[A-Z0-9\-]{5,}\b", q, flags=re.IGNORECASE)
    if product_match:
        product_code = product_match.group(0)
        print(f"[chat] 偵測到產品品號: {product_code}")

        orders = db.query(Order).filter(Order.product_code == product_code).all()

        if orders:
            # 這裡簡單整理第一筆 + 數量統計給你看，確定真的有從 DB 抓到資料
            total_qty = sum(o.quantity for o in orders if getattr(o, "quantity", None) is not None)

            lines = [
                f"已為你查詢到產品品號 {product_code} 的訂單資訊：",
                f"- 相關訂單筆數：{len(orders)} 筆",
                f"- 總訂單數量：{total_qty}",
                "",
                "以下列出第一筆訂單作為代表：",
            ]

            o0 = orders[0]
            raw_due = getattr(o0, "due_date", None)
            if isinstance(raw_due, str):
                due0 = raw_due
            elif raw_due is not None:
                due0 = raw_due.strftime("%Y/%m/%d")
            else:
                due0 = "未設定"

            status_value = getattr(o0, "status", None)
            status0 = getattr(status_value, "value", status_value) or "未設定"

            lines.extend(
                [
                    f"  - 訂單編號：{o0.order_number or '（未填寫）'}",
                    f"  - 客戶名稱：{o0.customer_name or '（未填寫）'}",
                    f"  - 訂單數量：{o0.quantity}",
                    f"  - 交期：{due0}",
                    f"  - 狀態：{status0}",
                ]
            )

            return ChatResponse(
                answer="\n".join(lines),
                model="db_lookup(product_code)",
            )

        # 這個品號在 DB 裡完全沒有訂單
        return ChatResponse(
            answer=(
                f"系統查不到產品品號「{product_code}」相關的訂單。\n"
                f"請確認品號是否正確，或先在訂單管理頁建立相關訂單資料。"
            ),
            model="db_lookup(product_code)",
        )

    # --------------------------------------------------
    # 3️⃣ 使用 Function Calling 處理一般查詢
    # --------------------------------------------------
    if not groq_client:
        raise HTTPException(
            status_code=500,
            detail="尚未設定 GROQ_API_KEY，無法呼叫聊天模型。",
        )

    system_prompt = (
        "你是個專業的發泡成型保麗龍工廠的生產排程系統決策支援助理，請使用繁體中文回答。\n\n"
        "【重要原則】\n"
        "1. **嚴格依據工具返回的實際數據回答**，絕對不可編造或猜測數字\n"
        "2. 工具返回的 total_count 或 total_orders 就是確切數量，請直接使用\n"
        "3. 如果數據為空（0筆），請明確告知用戶「目前沒有相關記錄」\n"
        "4. 提供分析時，基於實際數據給出專業建議\n\n"
        "可用工具：\n"
        "- get_orders_summary: 查詢訂單列表（返回 total_count 和 orders 清單）\n"
        "- get_order_statistics: 統計訂單狀態分布（返回 total_orders 和 by_status）\n"
        "- get_machine_schedule: 查詢機台排程\n"
        "- get_delayed_orders: 查詢延遲訂單（返回 total_count 和延遲訂單清單）\n"
        "- get_machine_utilization: 統計機台使用率\n"
        "- get_mold_info: 查詢模具資訊\n"
        "- get_completion_summary: 查詢完工記錄\n\n"
        "【回答要求】\n"
        "- 先說明查詢結果的數量（如：「查詢到 X 筆延遲訂單」）\n"
        "- 使用結構化格式呈現數據（如表格、清單）\n"
        "- 基於實際數據提供專業分析和建議\n"
        "- 每次回答保持一致性，不要給出不同的數字\n"
    )

    if req.context:
        system_prompt += (
            "\n\n以下是系統提供的背景說明，回答時可以參考：\n"
            f"{req.context}"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.question},
    ]

    try:
        # 第一次調用：讓 LLM 決定要用哪些工具
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=CHAT_TOOLS,
            tool_choice="auto"
        )

        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls

        # 如果 LLM 決定不使用工具，直接返回答案
        if not tool_calls:
            return ChatResponse(
                answer=response_message.content or "抱歉，我無法回答這個問題。",
                model="llama-3.3-70b-versatile",
            )

        # 執行工具調用
        messages.append(response_message)
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            
            print(f"[chat] 調用工具: {function_name}, 參數: {function_args}")
            
            # 執行對應的查詢函數
            if function_name == "get_orders_summary":
                function_response = get_orders_summary(db, **function_args)
            elif function_name == "get_order_statistics":
                function_response = get_order_statistics(db)
            elif function_name == "get_machine_schedule":
                function_response = get_machine_schedule(db, **function_args)
            elif function_name == "get_delayed_orders":
                function_response = get_delayed_orders(db)
            elif function_name == "get_machine_utilization":
                function_response = get_machine_utilization(db, **function_args)
            elif function_name == "get_mold_info":
                function_response = get_mold_info(db, **function_args)
            elif function_name == "get_completion_summary":
                function_response = get_completion_summary(db, **function_args)
            else:
                function_response = {"error": f"未知的工具: {function_name}"}
            
            # 將工具的回應加入對話
            print(f"[chat] 工具返回數據: {json.dumps(function_response, ensure_ascii=False)[:200]}...")
            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": json.dumps(function_response, ensure_ascii=False),
            })
        
        # 第二次調用：讓 LLM 基於工具結果生成最終答案
        print(f"[chat] 開始第二次 LLM 調用，基於 {len(tool_calls)} 個工具結果生成答案")
        final_response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.1  # 降低隨機性，提高一致性
        )
        
        answer = final_response.choices[0].message.content
        return ChatResponse(
            answer=answer or "已查詢完成，但無法生成回應。",
            model="llama-3.3-70b-versatile + function_calling",
        )
        
    except Exception as e:
        print(f"[chat] 錯誤: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chat 失敗: {e}",
        )


# 運行服務器
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
