"""驗證排程查詢能否正確過濾 quantity=0 的元件"""
from database import SessionLocal, ComponentSchedule

def check_scheduling_query():
    db = SessionLocal()
    try:
        # 模擬排程查詢 (加上 quantity > 0 過濾)
        components = db.query(ComponentSchedule).filter(
            ComponentSchedule.status == "未排程",
            ComponentSchedule.quantity > 0
        ).all()
        
        print(f"可排程元件數量: {len(components)}")
        
        # 檢查是否有 quantity=0 的漏網之魚
        zero_qty = [c for c in components if c.quantity == 0]
        if zero_qty:
            print(f"⚠️  發現 {len(zero_qty)} 個 quantity=0 的元件!")
        else:
            print("✅ 沒有 quantity=0 的元件會被排程")
        
        # 確認所有 quantity=0 的元件狀態都是"無法進行排程"
        all_zero_qty = db.query(ComponentSchedule).filter(
            ComponentSchedule.quantity == 0
        ).all()
        
        print(f"\n所有 quantity=0 的元件: {len(all_zero_qty)}")
        status_count = {}
        for c in all_zero_qty:
            status_count[c.status] = status_count.get(c.status, 0) + 1
        
        for status, count in status_count.items():
            print(f"  {status}: {count}")
        
    finally:
        db.close()

if __name__ == "__main__":
    check_scheduling_query()
