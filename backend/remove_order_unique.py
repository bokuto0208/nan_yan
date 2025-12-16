"""
移除 orders 表中 order_number 的 unique 限制
因為一個訂單號可能對應多個品號
"""
import sqlite3
import shutil
from datetime import datetime

def remove_unique_constraint():
    """重建 orders 表以移除 unique 限制"""
    
    # 備份資料庫
    backup_file = f"eps_system_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2('eps_system.db', backup_file)
    print(f"已備份資料庫到: {backup_file}")
    
    conn = sqlite3.connect('eps_system.db')
    cursor = conn.cursor()
    
    try:
        # SQLite 不支援直接修改約束，需要重建表
        
        # 1. 創建新表（沒有 unique 限制）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders_new (
                id TEXT PRIMARY KEY,
                order_number TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                product_code TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                priority INTEGER DEFAULT 3,
                status TEXT DEFAULT 'PENDING',
                scheduled_date TEXT,
                scheduled_start_time TEXT,
                scheduled_end_time TEXT,
                order_date TEXT,
                customer_id TEXT,
                order_sequence TEXT,
                undelivered_quantity INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. 複製資料
        cursor.execute("""
            INSERT INTO orders_new 
            SELECT * FROM orders
        """)
        
        # 3. 刪除舊表
        cursor.execute("DROP TABLE orders")
        
        # 4. 重命名新表
        cursor.execute("ALTER TABLE orders_new RENAME TO orders")
        
        conn.commit()
        print("✓ 成功移除 order_number 的 unique 限制")
        print("  現在一個訂單號可以對應多個品號")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 更新失敗: {e}")
        print(f"可以從備份恢復: {backup_file}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    remove_unique_constraint()
