"""
匯入 1階產品資料對照表（半成品）
從新版產品資料對照檔.xlsx匯入品號1開頭的半成品資料
"""
import pandas as pd
from database import SessionLocal, ProductOne, init_db
from datetime import datetime

def import_product_one():
    # 初始化資料庫
    init_db()
    
    # 讀取 Excel 檔案
    df = pd.read_excel('raw_data/新版產品資料對照檔.xlsx')
    
    # 清理欄位名稱（去除空白）
    df.columns = df.columns.str.strip()
    
    print(f"總共讀取 {len(df)} 筆資料")
    
    # 篩選品號為 1 開頭的半成品
    df_one = df[df['品    號'].astype(str).str.startswith('1')].copy()
    print(f"篩選出 {len(df_one)} 筆 1 開頭的半成品")
    
    # 建立資料庫連線
    db = SessionLocal()
    
    try:
        # 清空現有資料
        db.query(ProductOne).delete()
        db.commit()
        print("已清空舊資料")
        
        # 匯入新資料
        count = 0
        for _, row in df_one.iterrows():
            try:
                product_code = str(row['品    號']).strip()
                
                # 處理換模時間（換模/烘乾時間）- 轉換為分鐘並四捨五入，缺失時設為 0
                mold_change_time = 0
                if pd.notna(row['[換模/烘乾時間]']):
                    try:
                        mold_change_time = round(float(row['[換模/烘乾時間]']) * 60)
                    except (ValueError, TypeError):
                        mold_change_time = 0
                
                # 創建記錄
                product = ProductOne(
                    product_code=product_code,
                    mold_change_time=mold_change_time
                )
                
                db.add(product)
                count += 1
                
                if count % 100 == 0:
                    print(f"已處理 {count} 筆資料...")
                    
            except Exception as e:
                print(f"處理資料時發生錯誤: {row['品    號']} - {str(e)}")
                continue
        
        # 提交所有變更
        db.commit()
        print(f"\n✅ 成功匯入 {count} 筆 1階產品資料")
        
        # 顯示統計資訊
        total = db.query(ProductOne).count()
        with_mold_time = db.query(ProductOne).filter(ProductOne.mold_change_time > 0).count()
        
        print(f"\n統計資訊:")
        print(f"  總筆數: {total}")
        print(f"  有換模時間: {with_mold_time}")
        print(f"  無換模時間: {total - with_mold_time}")
        
        # 顯示前5筆範例
        print("\n前5筆資料範例:")
        samples = db.query(ProductOne).limit(5).all()
        for s in samples:
            print(f"  {s.product_code} - 換模:{s.mold_change_time}分")
        
    except Exception as e:
        db.rollback()
        print(f"❌ 匯入失敗: {str(e)}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import_product_one()
