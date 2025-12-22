"""
檢查 ComponentSchedule 表的資料狀況
"""
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from database import ComponentSchedule, Order

engine = create_engine('sqlite:///eps_system.db', echo=False)
Session = sessionmaker(bind=engine)
db = Session()

print("=" * 80)
print("ComponentSchedule 表分析")
print("=" * 80)

# 1. 總記錄數
total = db.query(ComponentSchedule).count()
print(f"\n總記錄數: {total}")

# 2. 按狀態統計
print("\n按狀態統計:")
status_stats = db.query(
    ComponentSchedule.status,
    func.count(ComponentSchedule.id)
).group_by(ComponentSchedule.status).all()

for status, count in status_stats:
    print(f"  {status}: {count} 筆 ({count/total*100:.1f}%)")

# 3. 按訂單統計
print("\n按訂單統計:")
order_stats = db.query(
    ComponentSchedule.order_id,
    func.count(ComponentSchedule.id)
).group_by(ComponentSchedule.order_id).all()

print(f"  不重複訂單數: {len(order_stats)}")
for order_id, count in order_stats[:5]:  # 只顯示前5個
    order = db.query(Order).filter(Order.id == order_id).first()
    order_num = order.order_number if order else "未知"
    print(f"  訂單 {order_num}: {count} 筆子件")

# 4. 查看未排程的子件
print("\n未排程的子件（前10筆）:")
unscheduled = db.query(ComponentSchedule).filter(
    ComponentSchedule.status == "未排程"
).limit(10).all()

for cs in unscheduled:
    order = db.query(Order).filter(Order.id == cs.order_id).first()
    order_num = order.order_number if order else "未知"
    print(f"  訂單 {order_num}: {cs.component_code} (數量: {cs.quantity})")

# 5. 查看模具狀態的子件
print("\n模具狀態的子件:")
mold_status = db.query(ComponentSchedule).filter(
    ComponentSchedule.status == "模具"
).all()

if mold_status:
    mold_components = set(cs.component_code for cs in mold_status)
    print(f"  總計 {len(mold_status)} 筆，{len(mold_components)} 個不同品號")
    for comp in list(mold_components)[:5]:
        print(f"    - {comp}")
else:
    print("  無")

# 6. 查看無法排程的子件
print("\n無法進行排程的子件:")
cannot_schedule = db.query(ComponentSchedule).filter(
    ComponentSchedule.status == "無法進行排程"
).all()

if cannot_schedule:
    cannot_components = set(cs.component_code for cs in cannot_schedule)
    print(f"  總計 {len(cannot_schedule)} 筆，{len(cannot_components)} 個不同品號")
    for comp in list(cannot_components)[:5]:
        print(f"    - {comp}")
else:
    print("  無")

# 7. 說明
print("\n" + "=" * 80)
print("ComponentSchedule 表的用途：")
print("=" * 80)
print("""
這個表記錄訂單拆解後的「子件排程記錄」：

1. 訂單匯入時：
   - 根據 BOM 將訂單（0開頭成品）拆解成子件（1/6開頭）
   - 每個子件創建一筆 ComponentSchedule 記錄
   - 初始狀態：未排程 / 模具 / 無法進行排程

2. 排程執行時：
   - 排程引擎讀取「未排程」狀態的子件
   - 排程後更新為「已排程」並填入機台、時間等資訊
   - 「模具」和「無法進行排程」不參與排程

3. 目前問題：
   - 如果有很多「未排程」，代表這些子件還沒執行排程
   - 需要在排程頁面點擊「開始排程」按鈕來排程
""")

db.close()
