"""
BOM CSV 資料導入腳本

此腳本將 raw_data/BOM.csv 中的數據導入到資料庫的 bom 表中。

處理規則:
1. 只處理查詢品號為 0 開頭的完成品
2. 只處理階次及子件料號為 1 開頭的子件(半成品) 或 6 開頭的模具
3. 穴數 = 1 / 單位用量 (四捨五入到整數)
4. 儲存: 品號ID, 子件/模具ID, 穴數
"""

import csv
import sys
from pathlib import Path
from sqlalchemy.orm import Session
from database import SessionLocal, BOM, Base, engine

def import_bom_from_csv(csv_path: str):
    """從 CSV 導入 BOM 資料"""
    
    # 確保資料表存在
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # 先清空現有的 BOM 資料
        print("清除現有 BOM 資料...")
        db.query(BOM).delete()
        db.commit()
        
        # 讀取 CSV (嘗試不同編碼)
        print(f"讀取 CSV 檔案: {csv_path}")
        
        # 嘗試不同的編碼
        encodings = ['utf-8-sig', 'big5', 'gbk', 'cp950', 'latin1']
        reader = None
        f = None
        
        for encoding in encodings:
            try:
                f = open(csv_path, 'r', encoding=encoding)
                reader = csv.DictReader(f)
                # 嘗試讀取第一行來驗證編碼
                next(reader)
                # 如果成功，重新打開檔案
                f.close()
                f = open(csv_path, 'r', encoding=encoding)
                reader = csv.DictReader(f)
                print(f"使用編碼: {encoding}")
                break
            except (UnicodeDecodeError, StopIteration):
                if f:
                    f.close()
                continue
        
        if not reader:
            raise ValueError("無法找到正確的檔案編碼")
        
        imported_count = 0
        skipped_count = 0
        
        for row in reader:
            product_code = row['查詢品號'].strip()
            component_raw = row['階次及子件料號'].strip()
            unit_usage = float(row['單位用量'])
            
            # 規則 1: 只處理 0 開頭的品號
            if not product_code.startswith('0'):
                skipped_count += 1
                continue
            
            # 提取子件/模具料號 (移除所有的 "。" 字符)
            component_code = component_raw.replace('。', '')
            
            # 規則 2: 只處理 1 開頭的子件料號 或 6 開頭的模具料號
            if not (component_code.startswith('1') or component_code.startswith('6')):
                skipped_count += 1
                continue
            
            # 規則 3: 穴數 = 1 / 單位用量
            if unit_usage == 0:
                print(f"警告: {product_code} -> {component_code} 的單位用量為 0，跳過")
                skipped_count += 1
                continue
            
            cavity_count = round(1 / unit_usage)
            
            # 檢查是否已存在相同的記錄
            existing = db.query(BOM).filter(
                BOM.product_code == product_code,
                BOM.component_code == component_code
            ).first()
            
            if existing:
                # 更新穴數
                existing.cavity_count = cavity_count
                print(f"更新: {product_code} -> {component_code}, 穴數: {cavity_count}")
            else:
                # 新增記錄
                bom_entry = BOM(
                    product_code=product_code,
                    component_code=component_code,
                    cavity_count=cavity_count
                )
                db.add(bom_entry)
                print(f"新增: {product_code} -> {component_code}, 穴數: {cavity_count}")
            
            imported_count += 1
        
        # 提交所有變更
        db.commit()
        
        # 關閉檔案
        if f:
            f.close()
        
        print("\n" + "="*60)
        print(f"✓ 導入完成！")
        print(f"  - 成功導入: {imported_count} 筆")
        print(f"  - 跳過: {skipped_count} 筆")
        print("="*60)
            
    except Exception as e:
        print(f"✗ 錯誤: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def show_sample_data():
    """顯示部分導入的資料"""
    db = SessionLocal()
    try:
        print("\n前 10 筆 BOM 資料:")
        print("-" * 80)
        print(f"{'品號ID':<20} {'子件ID':<20} {'穴數':>10}")
        print("-" * 80)
        
        bom_entries = db.query(BOM).limit(10).all()
        for entry in bom_entries:
            print(f"{entry.product_code:<20} {entry.component_code:<20} {entry.cavity_count:>10}")
        
        total_count = db.query(BOM).count()
        print("-" * 80)
        print(f"總共 {total_count} 筆資料")
        
    finally:
        db.close()

if __name__ == "__main__":
    # CSV 檔案路徑
    csv_file = Path(__file__).parent / "raw_data" / "BOM.csv"
    
    if not csv_file.exists():
        print(f"✗ 錯誤: 找不到檔案 {csv_file}")
        sys.exit(1)
    
    print("開始導入 BOM 資料...")
    print("="*60)
    
    import_bom_from_csv(str(csv_file))
    show_sample_data()
