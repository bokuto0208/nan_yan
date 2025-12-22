"""修正資料庫中 quantity=0 的已排程元件"""
from database import SessionLocal, ComponentSchedule

def fix_zero_quantity_components():
    db = SessionLocal()
    try:
        # 找出 quantity=0 的元件
        zero_qty_components = db.query(ComponentSchedule).filter(
            ComponentSchedule.quantity == 0
        ).all()
        
        print(f"找到 {len(zero_qty_components)} 個數量為0的元件")
        
        updated = 0
        for component in zero_qty_components:
            # 將狀態改為"無法進行排程"，並清空排程時間
            component.status = "無法進行排程"
            component.scheduled_start = None
            component.scheduled_end = None
            component.machine_id = None
            updated += 1
        
        db.commit()
        print(f"✅ 已更新 {updated} 個元件的狀態")
        
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fix_zero_quantity_components()
