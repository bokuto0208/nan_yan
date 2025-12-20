from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict
import uvicorn
import uuid
import math
import os
import shutil
from datetime import datetime

from database import get_db, init_db, Order, Downtime, MachineProductHistory, Machine, Component, BOM, ComponentSchedule, Completion
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

# 初始化 FastAPI 應用
app = FastAPI(title="EPS System API", version="1.0.0")

# CORS 設置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5174",
        "http://localhost:51730",
        "http://127.0.0.1:51730",
        "http://localhost:51731",
        "http://127.0.0.1:51731"
    ],
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
        component_schedule = ComponentSchedule(
            id=str(uuid.uuid4()),
            order_id=new_order.id,
            component_code=component_code,
            quantity=total_quantity,
            status="PENDING"
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
            component_schedule = ComponentSchedule(
                id=str(uuid.uuid4()),
                order_id=order_id,
                component_code=component_code,
                quantity=total_quantity,
                status="PENDING"
            )
            db.add(component_schedule)
    
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str, db: Session = Depends(get_db)):
    """刪除訂單"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    db.delete(order)
    db.commit()
    return {"message": "Order deleted successfully"}

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
            "skipped": result["skipped"]
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
    from database import Product
    
    orders = db.query(Order).all()
    result = []
    
    for order in orders:
        # 獲取該訂單的所有產品
        products = db.query(Product).filter(Product.order_id == order.id).all()
        
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
            "due_date": order.due_date,
            "priority": order.priority,
            "status": order.status,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "products": products_with_components
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
        component_schedule = ComponentSchedule(
            id=str(uuid.uuid4()),
            order_id=order.id,
            component_code=component_code,
            quantity=total_quantity,
            status="PENDING"
        )
        db.add(component_schedule)
        created_count += 1
    
    db.commit()
    return {
        "message": f"Expanded {created_count} components for order {order.order_number}",
        "order_id": order_id,
        "components_created": created_count
    }

# 運行服務器
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
