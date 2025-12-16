from database import SessionLocal, Inventory, init_db
import csv
import chardet

def import_inventory_from_csv(csv_path):
    # 檢測檔案編碼
    with open(csv_path, 'rb') as f:
        result = chardet.detect(f.read())
        encoding = result['encoding']
    
    print(f"檢測到檔案編碼: {encoding}")
    
    # 初始化資料庫
    init_db()
    
    db = SessionLocal()
    
    try:
        # 清空現有庫存資料
        db.query(Inventory).delete()
        db.commit()
        print("已清空現有庫存資料")
        
        imported_count = 0
        skipped_count = 0
        
        # 讀取CSV檔案
        with open(csv_path, 'r', encoding=encoding) as csvfile:
            # 讀取第一行作為標題
            first_line = csvfile.readline().strip()
            print(f"CSV標題行: {first_line}")
            
            # 重新定位到檔案開頭
            csvfile.seek(0)
            reader = csv.reader(csvfile)
            
            # 跳過標題行
            next(reader)
            
            for row in reader:
                try:
                    # CSV格式: 品號,庫存數量
                    if len(row) < 2:
                        skipped_count += 1
                        continue
                    
                    product_code = row[0].strip()
                    quantity_str = row[1].strip()
                    
                    # 驗證資料
                    if not product_code:
                        skipped_count += 1
                        continue
                    
                    # 轉換數量
                    try:
                        quantity = int(quantity_str)
                    except (ValueError, TypeError):
                        print(f"警告: 品號 {product_code} 的數量格式錯誤: {quantity_str}，設為 0")
                        quantity = 0
                    
                    # 建立庫存記錄
                    inventory = Inventory(
                        product_code=product_code,
                        quantity=quantity
                    )
                    
                    db.add(inventory)
                    imported_count += 1
                    
                    if imported_count % 100 == 0:
                        print(f"已匯入 {imported_count} 筆庫存資料...")
                    
                except Exception as e:
                    print(f"處理行時發生錯誤: {e}")
                    skipped_count += 1
                    continue
        
        # 提交所有變更
        db.commit()
        print(f"\n庫存資料匯入完成！")
        print(f"成功匯入: {imported_count} 筆")
        print(f"跳過: {skipped_count} 筆")
        
        return {
            "imported": imported_count,
            "skipped": skipped_count
        }
        
    except Exception as e:
        db.rollback()
        print(f"匯入失敗: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    csv_path = "raw_data/inventory.csv"
    result = import_inventory_from_csv(csv_path)
    print(f"\n最終結果: {result}")
