"""
新增 daily_schedule_blocks 資料表
儲存每日分段的排程資料
"""
from database import Base, engine, DailyScheduleBlock

def migrate():
    print("開始建立 daily_schedule_blocks 表...")
    
    # 創建表（如果不存在）
    Base.metadata.create_all(bind=engine, tables=[DailyScheduleBlock.__table__])
    
    print("✅ daily_schedule_blocks 表建立完成")
    print("\n表結構:")
    print("- id: 主鍵 (自增)")
    print("- order_id: 製令號（關聯到 ComponentSchedule.id）")
    print("- component_code: 品號")
    print("- machine_id: 機台編號")
    print("- scheduled_date: 日期 (YYYY-MM-DD)")
    print("- start_time: 開始時間")
    print("- end_time: 結束時間")
    print("- sequence: 第幾段 (1, 2, 3...)")
    print("- total_sequences: 總共幾段")
    print("- previous_block_id: 前一段的 ID")
    print("- next_block_id: 後一段的 ID")
    print("- status: 狀態")
    print("- created_at: 建立時間")
    print("- updated_at: 更新時間")

if __name__ == "__main__":
    migrate()
