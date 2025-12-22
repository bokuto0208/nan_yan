"""
移除 DailyScheduleBlock 表中的 schedule_id 欄位
只保留 order_id
"""
from sqlalchemy import create_engine, text

DATABASE_URL = "sqlite:///./eps_system.db"
engine = create_engine(DATABASE_URL)

def migrate():
    print("開始遷移：移除 schedule_id 欄位...")
    
    with engine.begin() as conn:
        # SQLite 不支援直接 DROP COLUMN，需要重建表
        print("1. 創建臨時表...")
        conn.execute(text("""
            CREATE TABLE daily_schedule_blocks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id VARCHAR NOT NULL,
                component_code VARCHAR NOT NULL,
                machine_id VARCHAR NOT NULL,
                scheduled_date VARCHAR NOT NULL,
                start_time DATETIME NOT NULL,
                end_time DATETIME NOT NULL,
                sequence INTEGER NOT NULL,
                total_sequences INTEGER NOT NULL,
                previous_block_id INTEGER,
                next_block_id INTEGER,
                status VARCHAR DEFAULT 'PENDING',
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        
        print("2. 複製資料（使用 order_id）...")
        conn.execute(text("""
            INSERT INTO daily_schedule_blocks_new 
            (id, order_id, component_code, machine_id, scheduled_date, 
             start_time, end_time, sequence, total_sequences, 
             previous_block_id, next_block_id, status, created_at, updated_at)
            SELECT 
                id, order_id, component_code, machine_id, scheduled_date,
                start_time, end_time, sequence, total_sequences,
                previous_block_id, next_block_id, status, created_at, updated_at
            FROM daily_schedule_blocks
        """))
        
        print("3. 刪除舊表...")
        conn.execute(text("DROP TABLE daily_schedule_blocks"))
        
        print("4. 重命名新表...")
        conn.execute(text("ALTER TABLE daily_schedule_blocks_new RENAME TO daily_schedule_blocks"))
    
    print("✅ 遷移完成！已移除 schedule_id 欄位")

if __name__ == "__main__":
    migrate()
