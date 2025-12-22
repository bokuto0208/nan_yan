# -*- coding: utf-8 -*-
"""
模具生產需求計算工具（從資料庫讀取版）

風格：
1. 訂單總量 = 未交數量
2. 需生產量 = 未交數量 - 庫存
3. 穴數：優先模具資料表，沒有就用 1 / 單位用量
4. ❗ 若沒有模具編號 → 直接剔除，不輸出
5. ❗ 不輸出「穴數_from_BOM」「穴數_最終」「訂單編號列表」
"""

import pandas as pd
import numpy as np
import math
import re
import os
import uuid
from datetime import datetime
from database import SessionLocal, Order, BOM, MoldData, ProductZero, ProductOne, Inventory, Product, MoldCalculation

# ================== 設定區 ==================

OUTPUT_FILE = "計算結果.xlsx"

# 計算欄位
COL_NEEDED_QTY = "需生產量"
COL_MOLD_ID = "模具編號"
COL_CAVITY = "穴數"
COL_SHOTS = "所需模次"
COL_MOLD_CHANGE_TIME = "換模時間(分)"
COL_TOTAL_SEC = "總成型時間(秒)"
COL_TOTAL_WITH_CHANGE = "含換模總時間(分)"


# ================== 工具 ==================

def extract_mold_code(text):
    """從 BOM 模具欄抓出 6 開頭編號"""
    if not isinstance(text, str):
        return None
    m = re.search(r"(?<![0-9A-Za-z])6[0-9A-Za-z]+", text)
    return m.group(0) if m else None


# ================== 資料庫讀取 ==================

def load_orders_from_db():
    """從資料庫讀取訂單資料"""
    db = SessionLocal()
    try:
        orders = db.query(Order).all()
        data = []
        for order in orders:
            data.append({
                'order_id': order.id,
                'product_code': order.product_code,
                'undelivered_quantity': order.undelivered_quantity or 0
            })
        return pd.DataFrame(data)
    finally:
        db.close()


def load_inventory_from_db():
    """從資料庫讀取庫存資料"""
    db = SessionLocal()
    try:
        inventory_items = db.query(Inventory).all()
        data = []
        for inv in inventory_items:
            data.append({
                'product_code': inv.product_code,
                'inventory_quantity': inv.quantity or 0
            })
        return pd.DataFrame(data)
    finally:
        db.close()


def load_mold_data_from_db():
    """從資料庫讀取模具資料表（包含完整資訊）"""
    db = SessionLocal()
    try:
        mold_items = db.query(MoldData).all()
        data = []
        for mold in mold_items:
            data.append({
                'product_code': mold.product_code,
                'component_code': mold.component_code,
                'mold_code': mold.mold_code,
                'machine_id': mold.machine_id,
                'cavity_count': mold.cavity_count,
                'avg_molding_time': mold.avg_molding_time
            })
        return pd.DataFrame(data)
    finally:
        db.close()


def load_product_times_from_db():
    """從資料庫讀取產品時間資料（0階和1階）"""
    db = SessionLocal()
    try:
        # 0階產品（烘乾時間當作換模時間）
        zero_products = db.query(ProductZero).all()
        data = []
        for p in zero_products:
            data.append({
                'product_code': p.product_code,
                'mold_change_time': p.drying_time or 0  # 分鐘
            })
        
        # 1階產品（換模時間）
        one_products = db.query(ProductOne).all()
        for p in one_products:
            data.append({
                'product_code': p.product_code,
                'mold_change_time': p.mold_change_time or 0  # 分鐘
            })
        
        return pd.DataFrame(data)
    finally:
        db.close()


# ================== 主程式 ==================

def calculate_and_save(silent=False, save_excel=True):
    """執行模具計算並儲存至資料庫
    
    Args:
        silent: 是否靜默模式（不輸出訊息）
        save_excel: 是否產生 Excel 檔案
    
    Returns:
        dict: 包含成功狀態和計算結果的字典
    """
    if not silent:
        print("從資料庫讀取資料中...")

    output_file = None
    if save_excel:
        # 嘗試刪除舊檔案，如果被開啟則使用新檔名
        output_file = OUTPUT_FILE
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except PermissionError:
                if not silent:
                    print(f"⚠️  警告：{output_file} 正在使用中，將改用新檔名")
                output_file = f"計算結果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    # 從資料庫讀取
    orders = load_orders_from_db()
    inventory = load_inventory_from_db()
    mold = load_mold_data_from_db()
    product_times = load_product_times_from_db()
    
    if orders.empty:
        if not silent:
            print("❌ 沒有訂單資料")
        return {"success": False, "message": "沒有訂單資料"}
    
    if mold.empty:
        if not silent:
            print("❌ 沒有模具資料")
        return {"success": False, "message": "沒有模具資料"}

    # 訂單彙總（取未交數量）
    order_sum = (
        orders.groupby('product_code', as_index=False)['undelivered_quantity']
        .sum()
        .rename(columns={'undelivered_quantity': '訂單總量'})
    )

    # 合併庫存
    if not inventory.empty:
        order_sum = order_sum.merge(
            inventory,
            on='product_code',
            how='left'
        )
        order_sum['庫存總量'] = order_sum['inventory_quantity'].fillna(0)
    else:
        order_sum['庫存總量'] = 0

    order_sum[COL_NEEDED_QTY] = order_sum['訂單總量'] - order_sum['庫存總量']
    order_sum[COL_NEEDED_QTY] = order_sum[COL_NEEDED_QTY].clip(lower=0)

    # 直接使用模具資料表（已包含 product_code, mold_code, cavity_count 等）
    df = order_sum.merge(mold, on='product_code', how='left')
    
    # 記錄過濾的品號和原因
    warnings = []
    all_product_codes = set(df['product_code'].unique())

    # ⭐ 重點規則：沒有模具 → 直接剔除
    no_mold = df[df['mold_code'].isna()]['product_code'].unique()
    for code in no_mold:
        warnings.append(f"[品號:{code}]有排程資料上的缺失!無法列入排程 (原因: 無模具資料)")
    df = df[df['mold_code'].notna()].copy()

    # 只保留 6 開頭的模具編號
    invalid_mold = df[~df['mold_code'].str.startswith('6', na=False)]['product_code'].unique()
    for code in invalid_mold:
        warnings.append(f"[品號:{code}]有排程資料上的缺失!無法列入排程 (原因: 模具編號不正確)")
    df = df[df['mold_code'].str.startswith('6', na=False)].copy()

    # 再次篩選：若機台編號或穴數為空 → 剔除
    missing_data = df[(df['machine_id'].isna()) | (df['cavity_count'].isna()) | (df['cavity_count'] <= 0)]['product_code'].unique()
    for code in missing_data:
        warnings.append(f"[品號:{code}]有排程資料上的缺失!無法列入排程 (原因: 機台編號或穴數資料不完整)")
    df = df[df['machine_id'].notna() & df['cavity_count'].notna() & (df['cavity_count'] > 0)].copy()

    # 重命名欄位
    df = df.rename(columns={
        'mold_code': COL_MOLD_ID,
        'machine_id': '機台編號',
        'cavity_count': COL_CAVITY,
        'avg_molding_time': '平均成型時間(秒)'
    })

    # 合併換模時間（先用 product_code 找，找不到用 component_code 找）
    if not product_times.empty:
        # 先用 product_code 合併
        df = df.merge(
            product_times.rename(columns={'mold_change_time': COL_MOLD_CHANGE_TIME}),
            on='product_code',
            how='left'
        )
        
        # 對於沒找到的，用 component_code 再試一次
        missing_mask = df[COL_MOLD_CHANGE_TIME].isna()
        if missing_mask.any() and 'component_code' in df.columns:
            comp_times = product_times.rename(columns={
                'product_code': 'component_code',
                'mold_change_time': 'comp_change_time'
            })
            df = df.merge(comp_times, on='component_code', how='left')
            df.loc[missing_mask, COL_MOLD_CHANGE_TIME] = df.loc[missing_mask, 'comp_change_time']
            df = df.drop(columns=['comp_change_time'], errors='ignore')
        
        df[COL_MOLD_CHANGE_TIME] = df[COL_MOLD_CHANGE_TIME].fillna(0)
    else:
        df[COL_MOLD_CHANGE_TIME] = 0

    # 模次
    df[COL_SHOTS] = df.apply(
        lambda r: math.ceil(r[COL_NEEDED_QTY] / r[COL_CAVITY]) 
        if r[COL_CAVITY] > 0 else 0,
        axis=1
    )

    # 總成型時間（秒）
    df[COL_TOTAL_SEC] = df[COL_SHOTS] * df['平均成型時間(秒)']

    # 含換模總時間（分鐘）= 總成型時間/60 + 換模時間
    # 特殊處理：如果需生產量為 0，總時間也設為 0
    df[COL_TOTAL_WITH_CHANGE] = df.apply(
        lambda r: 0 if r[COL_NEEDED_QTY] == 0 else (r[COL_TOTAL_SEC] / 60) + r[COL_MOLD_CHANGE_TIME],
        axis=1
    )

    # 輸出欄位（保留 component_code 以便寫入資料庫）
    final_cols = [
        'product_code',
        'component_code',  # 保留子件品號
        '訂單總量',
        '庫存總量',
        COL_NEEDED_QTY,
        COL_MOLD_ID,
        '機台編號',
        COL_CAVITY,
        COL_SHOTS,
        '平均成型時間(秒)',
        COL_MOLD_CHANGE_TIME,
        COL_TOTAL_SEC,
        COL_TOTAL_WITH_CHANGE,
    ]

    # 重新命名以符合原本格式
    df = df[final_cols].rename(columns={'product_code': '品號'})

    # 產生 Excel 檔案（如果需要）
    if save_excel and output_file:
        df.to_excel(output_file, index=False)
        if not silent:
            print(f"✅ 完成！已產生檔案：{output_file}")
    
    if not silent:
        print(f"   共計算 {len(df)} 筆資料")
        print(f"   平均換模時間：{df[COL_MOLD_CHANGE_TIME].mean():.1f} 分鐘")
        print(f"   平均含換模總時間：{df[COL_TOTAL_WITH_CHANGE].mean():.1f} 分鐘")
    
    # 寫入資料庫 MoldCalculation（參考資料用）
    if not silent:
        print("\n開始寫入參考資料至資料庫...")
    result = save_to_mold_calculation(df, silent=silent)
    
    # 輸出警示訊息
    if warnings and not silent:
        print("\n⚠️  警示訊息:")
        for warning in warnings:
            print(f"  {warning}")
    
    return {
        "success": True,
        "count": len(df),
        "avg_mold_change_time": df[COL_MOLD_CHANGE_TIME].mean(),
        "avg_total_time": df[COL_TOTAL_WITH_CHANGE].mean(),
        "warnings": warnings
    }


def save_to_mold_calculation(df, silent=False):
    """將計算結果寫入 MoldCalculation 表（供排程邏輯參考用）"""
    session = SessionLocal()
    try:
        # 清除舊資料
        deleted = session.query(MoldCalculation).delete()
        session.commit()
        if not silent:
            print(f"   清除舊資料：{deleted} 筆")
        
        inserted_count = 0
        for _, row in df.iterrows():
            # 建立 MoldCalculation 記錄
            calc = MoldCalculation(
                product_code=row['品號'],
                component_code=row.get('component_code'),
                order_total=int(row['訂單總量']),
                inventory_total=int(row['庫存總量']),
                needed_quantity=int(row[COL_NEEDED_QTY]),
                mold_code=row[COL_MOLD_ID],
                machine_id=row['機台編號'],
                cavity_count=float(row[COL_CAVITY]),
                shot_count=int(row[COL_SHOTS]),
                avg_molding_time_sec=float(row['平均成型時間(秒)']),
                mold_change_time_min=float(row[COL_MOLD_CHANGE_TIME]),
                total_time_sec=float(row[COL_TOTAL_SEC]),
                total_time_with_change_min=float(row[COL_TOTAL_WITH_CHANGE]),
                created_at=datetime.utcnow()
            )
            
            session.add(calc)
            inserted_count += 1
        
        session.commit()
        if not silent:
            print(f"   成功寫入 {inserted_count} 筆參考資料到 mold_calculations 表")
        return inserted_count
        
    except Exception as e:
        session.rollback()
        if not silent:
            print(f"❌ 寫入資料庫失敗：{e}")
        raise
    finally:
        session.close()


def main():
    """命令列執行入口"""
    calculate_and_save(silent=False, save_excel=True)


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
