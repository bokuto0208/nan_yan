"""
模具資料表匯入腳本
從 raw_data/模具資料表.csv 匯入模具資料到資料庫
"""
import csv
import chardet
from database import SessionLocal, MoldData, init_db

def detect_encoding(file_path):
    """檢測文件編碼"""
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read())
        return result['encoding']

def import_mold_data():
    """匯入模具資料"""
    csv_file = "raw_data/模具資料表.csv"
    
    # 檢測編碼
    encoding = detect_encoding(csv_file)
    print(f"檢測到文件編碼: {encoding}")
    
    # 嘗試常見編碼
    encodings = [encoding, 'utf-8', 'big5', 'gbk', 'cp950']
    
    data = None
    for enc in encodings:
        try:
            with open(csv_file, 'r', encoding=enc) as f:
                data = list(csv.DictReader(f))
                print(f"成功使用 {enc} 編碼讀取文件")
                break
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    if not data:
        print("❌ 無法讀取CSV文件，所有編碼都失敗")
        return
    
    # 初始化資料庫
    init_db()
    db = SessionLocal()
    
    try:
        # 清空現有資料
        db.query(MoldData).delete()
        db.commit()
        print("已清空現有模具資料")
        
        imported_count = 0
        skipped_count = 0
        
        for row in data:
            try:
                # 提取欄位，處理空值
                product_code = row.get('成品品號', '').strip()
                component_code = row.get('子件品號(1開頭)', '').strip() or None
                mold_code = row.get('模具編號(6開頭)', '').strip()
                cavity_count_str = row.get('一模穴數', '').strip()
                machine_id = row.get('機台編號', '').strip() or None
                avg_molding_time_str = row.get('平均成型時間(秒)', '').strip()
                frequency_str = row.get('頻率', '').strip()
                yield_rank = row.get('良率排名', '').strip() or None
                
                # 必填欄位檢查
                if not product_code or not mold_code:
                    skipped_count += 1
                    continue
                
                # 轉換數值，處理空值
                try:
                    cavity_count = float(cavity_count_str) if cavity_count_str else None
                except ValueError:
                    cavity_count = None
                
                try:
                    avg_molding_time = float(avg_molding_time_str) if avg_molding_time_str else None
                except ValueError:
                    avg_molding_time = None
                
                try:
                    frequency = float(frequency_str) if frequency_str else None
                except ValueError:
                    frequency = None
                
                # 創建記錄
                mold_data = MoldData(
                    product_code=product_code,
                    component_code=component_code,
                    mold_code=mold_code,
                    cavity_count=cavity_count,
                    machine_id=machine_id,
                    avg_molding_time=avg_molding_time,
                    frequency=frequency,
                    yield_rank=yield_rank
                )
                db.add(mold_data)
                imported_count += 1
                
                # 每100筆提交一次
                if imported_count % 100 == 0:
                    db.commit()
                    print(f"已匯入 {imported_count} 筆...")
                
            except Exception as e:
                print(f"處理記錄時出錯: {row}, 錯誤: {e}")
                skipped_count += 1
                continue
        
        # 最後提交
        db.commit()
        
        print("\n" + "="*60)
        print(f"✓ 匯入完成！")
        print(f"  成功匯入: {imported_count} 筆")
        print(f"  跳過: {skipped_count} 筆")
        print("="*60)
        
        # 顯示前10筆資料作為驗證
        print("\n前10筆匯入的資料:")
        samples = db.query(MoldData).limit(10).all()
        for sample in samples:
            print(f"  {sample.product_code} -> {sample.component_code} -> {sample.mold_code} "
                  f"(穴數: {sample.cavity_count}, 機台: {sample.machine_id}, "
                  f"成型時間: {sample.avg_molding_time}秒)")
        
        # 統計資訊
        total = db.query(MoldData).count()
        print(f"\n資料庫中共有 {total} 筆模具資料")
        
    except Exception as e:
        db.rollback()
        print(f"❌ 匯入過程中發生錯誤: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import_mold_data()
