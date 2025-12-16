"""
更新訂單資料表結構
添加新欄位：order_date, customer_id, order_sequence, undelivered_quantity
"""
import sqlite3

def migrate_database():
    """更新資料庫結構"""
    conn = sqlite3.connect('eps_system.db')
    cursor = conn.cursor()
    
    try:
        # 檢查並添加新欄位
        columns_to_add = [
            ("order_date", "TEXT"),
            ("customer_id", "TEXT"),
            ("order_sequence", "TEXT"),
            ("undelivered_quantity", "INTEGER")
        ]
        
        for column_name, column_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {column_type}")
                print(f"✓ 添加欄位: {column_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print(f"  欄位 {column_name} 已存在，跳過")
                else:
                    raise
        
        conn.commit()
        print("\n資料庫結構更新完成！")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 更新失敗: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
