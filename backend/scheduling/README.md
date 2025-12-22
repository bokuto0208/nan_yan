# EPS 生產排程引擎

完整的半成品生產排程系統，支援多策略候選生成、智能選擇、訂單合併優化。

## 📋 目錄

- [系統架構](#系統架構)
- [核心模組](#核心模組)
- [排程流程](#排程流程)
- [使用示例](#使用示例)
- [配置選項](#配置選項)
- [測試](#測試)

## 系統架構

```
SchedulingEngine (主引擎)
    ├── TimeEstimator (時間估算)
    ├── ConstraintChecker (約束檢查)
    ├── ScheduleValidator (驗證器)
    ├── GapCalculator (時段計算)
    ├── CandidateGenerator (候選生成)
    ├── CandidateSelector (候選選擇)
    └── OrderMerger (訂單合併)
```

## 核心模組

### Phase 0: 基礎模組

#### models.py (214行)
- 資料模型定義
- **ManufacturingOrder**: 製令資料
- **MoldInfo**: 模具資訊
- **ScheduleCandidate**: 排程候選
- **ScheduleBlock**: 排程區塊
- **ScheduleResult**: 排程結果
- **SchedulingConfig**: 配置參數

#### time_estimator.py (217行)
- 時間計算引擎
- `calculate_forming_time()`: 成型時間 = (數量 / 穴數) × 平均成型時間 / 3600
- `calculate_total_time()`: 總時間 = 成型時間 + 換模時間
- `calculate_end_time()`: 計算結束時間（考慮工作日曆）
- `calculate_lateness()`: 計算延遲情況

**重要**: 僅計算半成品（1字頭品號），不包含烘乾時間

#### constraint_checker.py (304行)
- 約束條件檢查
- ✓ 工作日曆區間（WorkCalendarDay）
- ✓ 停機時段（Downtime）
- ✓ 換模禁止區（20:00-01:00）
- ✓ 模具並行衝突
- ✓ 機台時間重疊

### Phase 1: 統一驗證系統

#### validator.py (370行)
- 整合所有約束檢查
- **ValidationResult**: 驗證結果（is_valid, violations, warnings）
- **ConstraintViolation**: 違規詳情（type, message, severity, time_range）
- 支援單筆與批量驗證
- 7種違規類型：工作時間、停機、換模禁區、模具衝突、機台衝突、時間不足、約束不符

### Phase 2: 候選生成

#### gap_calculator.py (269行)
- 時段間隙計算
- **TimeGap**: 可用時段（start, end, duration, is_downtime）
- `calculate_machine_gaps()`: 找出機台可用時段
- `find_earliest_feasible_time()`: EFT搜尋演算法

#### candidate_generator.py (310行)
- 多策略候選生成
- **ASAP** (As Soon As Possible): 從間隙開始
- **JIT** (Just In Time): 從交期反推
- **MID**: 間隙中點開始
- **EFT** (Earliest Feasible Time): 最早可行時間
- 每個製令生成約25個候選（5機台 × 5策略）
- 所有候選通過驗證器檢查

### Phase 3: 候選評估選擇

#### candidate_selector.py (370行)
- 智能候選選擇
- **CandidateScore**: 計算評分（lateness, forming_time, yield, frequency）
- **4級決勝規則**:
  1. 交期（lateness_hours）- 最小延遲
  2. 成型時間 - 差距≥10%閾值時選較短
  3. 良率等級 - A(1) > B(2) > C(3)
  4. 上機頻率 - 選最常用模具
- **CandidateComparator**: 詳細比較邏輯

### Phase 4: 訂單合併

#### order_merger.py (380行)
- 合併優化
- **MergeGroup**: 按（品號, 機台）分組
- **MergeEvaluation**: 合併評估結果
- 交期窗口過濾（可配置1-5週）
- 換模時間節省：(N-1) × 換模時間
- 驗證合併排程可行性
- 確保所有訂單在最早交期前完成

**測試結果**: 5訂單合併節省8小時換模時間（5次→1次）

### Phase 5: 完整引擎整合

#### scheduling_engine.py (458行)
- 主排程引擎
- **核心功能**:
  - `schedule()`: 完整排程
  - `incremental_schedule()`: 增量排程
  - `reschedule()`: 重新排程
  - `validate_schedule()`: 驗證排程
  - `generate_schedule_report()`: 生成報告
  
- **排程流程**:
  1. 按交期與優先級排序
  2. 識別合併機會（如啟用）
  3. 處理合併訂單
  4. 逐個排程剩餘訂單
  5. 計算KPI與延遲報告
  6. 驗證結果

## 排程流程

```
輸入: 製令列表 + 現有排程
  ↓
[1] 按交期排序
  ↓
[2] 啟用合併? ──→ YES ──→ [2a] 批量生成候選
  │                         ↓
  │                      [2b] 識別合併組
  │                         ↓
  │                      [2c] 評估合併可行性
  │                         ↓
  │                      [2d] 創建合併區塊
  ↓                         ↓
[3] 逐個處理剩餘訂單 ←──────┘
  ↓
[4] 為單個訂單生成候選（基於當前區塊）
  ↓
[5] 選擇最佳候選（4級決勝）
  ↓
[6] 創建排程區塊
  ↓
[7] 更新當前區塊列表（供下個訂單使用）
  ↓
重複 [4-7] 直到所有訂單處理完成
  ↓
[8] 計算KPI與報告
  ↓
輸出: ScheduleResult
```

## 使用示例

### 基本排程

```python
from database import get_db
from scheduling.models import ManufacturingOrder, SchedulingConfig
from scheduling.scheduling_engine import SchedulingEngine

db = next(get_db())

# 配置
config = SchedulingConfig(
    now_datetime=datetime.now(),
    merge_enabled=False
)

# 創建引擎
engine = SchedulingEngine(db, config)

# 創建訂單
mos = [
    ManufacturingOrder(
        id="MO-001",
        order_id="ORD-001",
        component_code="1J20342PFC0200D0",
        product_code="0J20342PFC0200D0",
        quantity=500,
        ship_due=datetime(2025, 12, 24, 6, 40),
        status="PENDING"
    )
]

# 執行排程
result = engine.schedule(mos)

# 生成報告
report = engine.generate_schedule_report(result)
print(report)
```

### 啟用合併

```python
config = SchedulingConfig(
    merge_enabled=True,
    merge_window_weeks=2,  # 2週窗口
    merge_strategy=MergeStrategy.MERGE_WITHIN_DEADLINE
)

engine = SchedulingEngine(db, config)
result = engine.schedule(mos)
```

### 增量排程

```python
# 初始排程
initial_result = engine.schedule(initial_mos)

# 新增訂單
new_result = engine.incremental_schedule(new_mos, initial_result)
```

## 配置選項

### SchedulingConfig

| 參數 | 類型 | 預設值 | 說明 |
|------|------|--------|------|
| `now_datetime` | datetime | - | 當前時間 |
| `lookahead_days` | int | 30 | 向前查看天數 |
| `merge_enabled` | bool | False | 啟用訂單合併 |
| `merge_window_weeks` | int | 2 | 合併窗口（週） |
| `merge_strategy` | MergeStrategy | MERGE_WITHIN_DEADLINE | 合併策略 |
| `time_threshold_pct` | int | 10 | 成型時間閾值(%) |
| `candidate_strategies` | List | [ASAP, JIT, MID, EFT] | 候選策略 |

## 測試

### 執行所有測試

```bash
# Phase 1: 驗證系統
python test_validator.py

# Phase 2: 候選生成
python test_candidate_generator.py

# Phase 3: 候選選擇
python test_candidate_selector.py

# Phase 4: 訂單合併
python test_order_merger.py

# Phase 5: 完整引擎
python test_scheduling_engine.py
```

### 測試覆蓋

- ✅ 時間計算（成型、換模、總時間）
- ✅ 約束檢查（工作時間、停機、換模禁區）
- ✅ 驗證系統（7種違規類型）
- ✅ 時段計算（間隙識別、EFT搜尋）
- ✅ 候選生成（4種策略、25候選/訂單）
- ✅ 候選選擇（4級決勝規則）
- ✅ 訂單合併（窗口過濾、換模節省）
- ✅ 完整排程（基本、合併、增量、驗證）

## 性能指標

### 測試結果

**Phase 2 - 候選生成**:
- 1個製令 → 25個候選
- 分布: A02(5), A03(5), A04(5), A08(5), A09(5)
- 全部可行（通過驗證）

**Phase 3 - 候選選擇**:
- 最佳: A09（頻率5.0勝出）
- 決勝: 頻率 > 良率 > 成型時間 > 交期

**Phase 4 - 訂單合併**:
- 5訂單 → 1合併區塊
- 節省: 8小時換模（5次→1次）
- 效率: 80%減少

**Phase 5 - 完整排程**:
- 2訂單: 100%成功率，0延遲
- 4訂單: 100%成功率，0延遲
- 驗證: 通過（無衝突）

## 資料要求

### 必要資料表

1. **Molds** (模具主檔)
   - component_code: 品號
   - machine_id: 機台
   - cavity_count: 穴數
   - avg_molding_time_s: 平均成型時間（秒）
   - changeover_time_minutes: 換模時間（分）
   - yield_rank: 良率等級
   - frequency: 上機頻率

2. **WorkCalendarDay** (工作日曆)
   - date: 日期
   - start_time: 開始時間
   - end_time: 結束時間

3. **Downtime** (停機記錄)
   - machine_id: 機台
   - start_time: 開始時間
   - end_time: 結束時間
   - reason: 原因

### 資料完整度

- 模具記錄: 6,911筆
- 完整記錄: 5,094筆（73.7%）
- 唯一品號: 2,455個
- 支援機台: 5台（A02, A03, A04, A08, A09）

## 限制與注意事項

1. **僅半成品排程**: 只處理1字頭品號，不含烘乾時間
2. **Python 3.8兼容**: 使用 `Tuple` 而非 `tuple` 型別提示
3. **換模禁區**: 20:00-01:00 禁止換模
4. **工作時間**: 依據 WorkCalendarDay 定義
5. **合併窗口**: 僅合併窗口內（可配1-5週）的訂單

## 開發歷程

- **Phase 0** (2025-12-20): 基礎模組（models, time_estimator, constraint_checker）
- **Phase 1** (2025-12-20): 統一驗證系統（validator, 7違規類型）
- **Phase 2** (2025-12-20): 候選生成（gap_calculator, candidate_generator, 4策略）
- **Phase 3** (2025-12-20): 候選選擇（candidate_selector, 4級決勝）
- **Phase 4** (2025-12-21): 訂單合併（order_merger, 換模優化）
- **Phase 5** (2025-12-21): 引擎整合（scheduling_engine, 完整流程）

## 下一步

1. **API整合**: 創建FastAPI端點
2. **前端對接**: 排程結果視覺化
3. **多目標優化**: 延遲最小化 + 換模最小化
4. **約束放鬆**: 無解時提供建議
5. **What-If分析**: 情境模擬

## 授權

內部專案，禁止外部使用。

---

**開發團隊**: EPS 生產系統開發組  
**完成日期**: 2025年12月21日  
**版本**: 1.0.0
