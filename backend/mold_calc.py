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
from database import SessionLocal, Order, BOM, MoldData

# ================== 設定區 ==================

OUTPUT_FILE = "計算結果.xlsx"

# 計算欄位
COL_NEEDED_QTY = "需生產量"
COL_MOLD_ID = "模具編號"
COL_CAVITY = "穴數"
COL_SHOTS = "所需模次"
COL_TOTAL_SEC = "總成型時間(秒)"


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
                'product_code': order.product_code,
                'undelivered_quantity': order.undelivered_quantity or 0
            })
        return pd.DataFrame(data)
    finally:
        db.close()


def load_bom_from_db():
    """從資料庫讀取 BOM 資料"""
    db = SessionLocal()
    try:
        bom_items = db.query(BOM).all()
        data = []
        for bom in bom_items:
            # cavity_count 是穴數，單位用量 = 1 / cavity_count
            unit_usage = 1.0 / bom.cavity_count if bom.cavity_count > 0 else None
            data.append({
                'product_code': bom.product_code,
                'component_code': bom.component_code,
                'cavity_count': bom.cavity_count,
                'unit_usage': unit_usage
            })
        return pd.DataFrame(data)
    finally:
        db.close()


def load_mold_data_from_db():
    """從資料庫讀取模具資料表"""
    db = SessionLocal()
    try:
        mold_items = db.query(MoldData).all()
        data = []
        for mold in mold_items:
            data.append({
                'mold_code': mold.mold_code,
                'machine_id': mold.machine_id,
                'cavity_count': mold.cavity_count,
                'avg_molding_time': mold.avg_molding_time
            })
        return pd.DataFrame(data)
    finally:
        db.close()


# ================== 主程式 ==================

def main():
    print("從資料庫讀取資料中...")

    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    # 從資料庫讀取
    orders = load_orders_from_db()
    bom = load_bom_from_db()
    mold = load_mold_data_from_db()
    
    if orders.empty:
        print("❌ 沒有訂單資料")
        return
    
    if bom.empty:
        print("❌ 沒有 BOM 資料")
        return
    
    if mold.empty:
        print("❌ 沒有模具資料")
        return

    # 訂單彙總（取未交數量）
    order_sum = (
        orders.groupby('product_code', as_index=False)['undelivered_quantity']
        .sum()
        .rename(columns={'undelivered_quantity': '訂單總量'})
    )

    # 目前系統沒有庫存表，假設庫存為 0
    order_sum['庫存總量'] = 0
    order_sum[COL_NEEDED_QTY] = order_sum['訂單總量']

    # 合併 BOM（使用 component_code 作為模具編號）
    bom2 = bom[['product_code', 'component_code', 'unit_usage']].copy()
    bom2 = bom2.rename(columns={'component_code': COL_MOLD_ID})
    
    df = order_sum.merge(bom2, on='product_code', how='left')

    # ⭐ 重點規則：沒有模具 → 直接剔除
    df = df[df[COL_MOLD_ID].notna()].copy()

    # 只保留 6 開頭的模具編號
    df = df[df[COL_MOLD_ID].str.startswith('6', na=False)].copy()

    # 合併模具資料
    mold2 = mold.rename(columns={
        'mold_code': COL_MOLD_ID,
        'machine_id': '機台編號',
        'cavity_count': '一模穴數',
        'avg_molding_time': '平均成型時間(秒)'
    })

    df = df.merge(mold2, on=COL_MOLD_ID, how='left')

    # 再次篩選：若模具資料表仍找不到資料 → 剔除
    df = df[df['機台編號'].notna()].copy()

    # 處理穴數
    df[COL_CAVITY] = df['一模穴數']

    # 若模具表穴數為空，用 BOM 單位用量反推
    fallback_mask = df[COL_CAVITY].isna() & df['unit_usage'].notna() & (df['unit_usage'] != 0)
    df.loc[fallback_mask, COL_CAVITY] = 1.0 / df['unit_usage']

    # 再篩選：沒有穴數 → 剔除
    df = df[df[COL_CAVITY].notna() & (df[COL_CAVITY] > 0)].copy()

    # 模次
    df[COL_SHOTS] = df.apply(
        lambda r: math.ceil(r[COL_NEEDED_QTY] / r[COL_CAVITY]) 
        if r[COL_CAVITY] > 0 else np.nan,
        axis=1
    )

    # 總成型時間
    df[COL_TOTAL_SEC] = df[COL_SHOTS] * df['平均成型時間(秒)']

    # 輸出欄位
    final_cols = [
        'product_code',
        '訂單總量',
        '庫存總量',
        COL_NEEDED_QTY,
        COL_MOLD_ID,
        '機台編號',
        COL_CAVITY,
        COL_SHOTS,
        '平均成型時間(秒)',
        COL_TOTAL_SEC,
    ]

    # 重新命名以符合原本格式
    df = df[final_cols].rename(columns={'product_code': '品號'})

    df.to_excel(OUTPUT_FILE, index=False)
    print(f"✅ 完成！已產生檔案：{OUTPUT_FILE}")
    print(f"   共計算 {len(df)} 筆資料")


if __name__ == "__main__":
    main()
