# 模具為單位的排程邏輯重構計劃

## 當前狀態分析 ✅

### 現有排程邏輯
- **製令單位**: 以 `ComponentSchedule`（子件）為單位
- **一對一關係**: 每個子件一個製令 (ManufacturingOrder)
- **問題**: 同一模具生產多個訂單的同一子件時，無法合併生產

### 現有數據結構
1. **Order** (訂單表)
   - 儲存訂單基本信息
   - order_number, product_code (0開頭成品), quantity, due_date等

2. **Product** (產品表)
   - 訂單展開後的產品
   - product_code可以是0開頭(成品)或1開頭(子件)或6開頭(模具)
   - quantity, undelivered_quantity

3. **ComponentSchedule** (元件排程表)
   - 目前的排程單位
   - component_code (1開頭子件), quantity, status

4. **BOM** (物料清單)
   - product_code (0開頭) → component_code (1開頭)
   - cavity_count (穴數)

5. **MoldData** (模具資料表)
   - product_code, component_code, mold_code (6開頭)
   - cavity_count, machine_id, avg_molding_time

6. **MoldCalculation** (模具計算表)
   - product_code, component_code, mold_code
   - cavity_count, shot_count (模次/回次)

### 模具與子件的關係
- 一個**模具**(6開頭) 可以生產 一個特定的**子件**(1開頭)
- 一個**子件**(1開頭) 對應 一個特定的**模具**(6開頭)
- 一個**成品**(0開頭) 需要 多個**子件**(1開頭)

## 新排程邏輯設計 🎯

### 核心概念
**以模具為單位生成製令，同一模具可以合併多個訂單的生產**

### 製令生成邏輯
```
輸入: 多個訂單 (每個訂單有不同的成品品號)
步驟:
1. 展開每個訂單的子件 (通過BOM)
2. 將子件轉換為模具需求 (通過MoldData查詢mold_code)
3. **按模具分組**所有訂單的需求
4. 為每個模具生成一個製令 (合併所有使用該模具的訂單)
5. 計算模具製令的總回次 = ceil(合併後總需求 / cavity_count)
6. 保留每個訂單在該模具製令中的份額

輸出: 模具製令列表 (MoldManufacturingOrder)
```

### 新數據結構設計

#### MoldManufacturingOrder (模具製令)
```python
class MoldManufacturingOrder:
    id: str                          # 製令ID
    mold_code: str                   # 模具編號 (6開頭)
    component_code: str              # 生產的子件編號 (1開頭)
    total_quantity: int              # 合併後總需求數量
    total_rounds: int                # 總回次 = ceil(total_quantity / cavity_count)
    cavity_count: int                # 穴數
    machine_id: str                  # 機台編號
    ship_due: datetime               # 最早交期 (所有訂單中的最早交期)
    priority: int                    # 最高優先級
    
    # 訂單份額追蹤
    order_details: List[MoldOrderDetail]  # 包含在此製令中的訂單明細
    
    # 排程結果
    scheduled_machine: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: str
```

#### MoldOrderDetail (模具製令中的訂單明細)
```python
class MoldOrderDetail:
    order_id: str                    # 訂單ID
    order_number: str                # 訂單號
    product_code: str                # 成品品號 (0開頭)
    component_quantity: int          # 此訂單需要的子件數量
    component_rounds: int            # 此訂單需要的回次
    due_date: datetime               # 此訂單的交期
    priority: int                    # 此訂單的優先級
```

### 資料庫Schema調整

#### 新增表: mold_manufacturing_orders (模具製令表)
```sql
CREATE TABLE mold_manufacturing_orders (
    id VARCHAR PRIMARY KEY,
    mold_code VARCHAR NOT NULL,
    component_code VARCHAR NOT NULL,
    total_quantity INTEGER NOT NULL,
    total_rounds INTEGER NOT NULL,
    cavity_count INTEGER NOT NULL,
    machine_id VARCHAR,
    earliest_due_date VARCHAR NOT NULL,
    highest_priority INTEGER NOT NULL,
    scheduled_machine VARCHAR,
    scheduled_start DATETIME,
    scheduled_end DATETIME,
    status VARCHAR DEFAULT 'PENDING',
    created_at DATETIME,
    updated_at DATETIME
);
```

#### 新增表: mold_order_details (模具製令訂單明細表)
```sql
CREATE TABLE mold_order_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mold_mo_id VARCHAR NOT NULL,        -- 關聯到 mold_manufacturing_orders.id
    order_id VARCHAR NOT NULL,
    order_number VARCHAR NOT NULL,
    product_code VARCHAR NOT NULL,
    component_quantity INTEGER NOT NULL,
    component_rounds INTEGER NOT NULL,
    due_date VARCHAR NOT NULL,
    priority INTEGER NOT NULL,
    FOREIGN KEY (mold_mo_id) REFERENCES mold_manufacturing_orders(id)
);
```

## 實施步驟 📋

### Step 1: 創建新的數據模型 ⏳
- [ ] 在 database.py 新增 MoldManufacturingOrder 表
- [ ] 在 database.py 新增 MoldOrderDetail 表
- [ ] 在 scheduling/models.py 新增 MoldMO 和 MoldOrderDetail 類

### Step 2: 實現模具製令生成器 ⏳
- [ ] 創建 backend/mold_mo_generator.py
- [ ] 實現按模具分組邏輯
- [ ] 實現訂單合併計算
- [ ] 實現回次計算

### Step 3: 修改排程API ⏳
- [ ] 修改 main.py 的 /api/scheduling/schedule endpoint
- [ ] 從 ComponentSchedule 改為生成 MoldMO
- [ ] 保留訂單追蹤信息

### Step 4: 調整排程引擎 ⏳
- [ ] 修改 SchedulingEngine 接收 MoldMO
- [ ] 調整 TimeEstimator 計算模具製令時間
- [ ] 保留合併訂單的交期檢查

### Step 5: 更新前端顯示 ⏳
- [ ] 修改排程結果顯示
- [ ] 顯示模具製令包含的多個訂單
- [ ] 顯示每個訂單的份額

### Step 6: 測試驗證 ⏳
- [ ] 創建測試案例: 同一模具多個訂單
- [ ] 驗證合併邏輯正確性
- [ ] 驗證回次計算正確性
- [ ] 驗證交期追蹤正確性

## 範例說明

### 場景
```
訂單A: SOD001 → 成品0A001 100個 (交期: 2025-12-25)
訂單B: SOD002 → 成品0B001 150個 (交期: 2025-12-26)
訂單C: SOD003 → 成品0A001 50個  (交期: 2025-12-24)

BOM展開:
- 0A001 需要 子件1X001 (模具6M001, 穴數4)
- 0B001 需要 子件1Y001 (模具6M002, 穴數2)
```

### 當前邏輯 (以子件為單位)
```
製令1: 訂單A → 子件1X001 100個 → 回次 ceil(100/4)=25
製令2: 訂單C → 子件1X001 50個  → 回次 ceil(50/4)=13
製令3: 訂單B → 子件1Y001 150個 → 回次 ceil(150/2)=75
總共: 3個製令
```

### 新邏輯 (以模具為單位)
```
模具製令1: 
- 模具6M001 → 子件1X001
- 合併: 訂單A(100個) + 訂單C(50個) = 150個
- 總回次: ceil(150/4) = 38回
- 最早交期: 2025-12-24 (訂單C)
- 包含訂單: [
    {order: SOD003, qty: 50, rounds: 13},
    {order: SOD001, qty: 100, rounds: 25}
  ]

模具製令2:
- 模具6M002 → 子件1Y001
- 數量: 150個
- 總回次: ceil(150/2) = 75回
- 交期: 2025-12-26
- 包含訂單: [{order: SOD002, qty: 150, rounds: 75}]

總共: 2個製令 (合併了使用相同模具的訂單)
```

## 優勢

1. **生產效率**: 同一模具連續生產，減少換模次數
2. **合併生產**: 多個訂單可以一次生產
3. **交期追蹤**: 保留每個訂單的交期信息
4. **彈性排程**: 可按最早交期優先排程

## 進度追蹤

- [x] 分析當前邏輯
- [x] 設計新結構
- [ ] 實施數據模型
- [ ] 實施生成邏輯
- [ ] 測試驗證
- [ ] 部署上線

---
更新時間: 2025-12-23
