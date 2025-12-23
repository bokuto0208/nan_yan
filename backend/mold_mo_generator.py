"""
模具製令生成器
將訂單按模具分組，生成以模具為單位的製令
"""
from sqlalchemy.orm import Session
from typing import List, Dict, Tuple
from collections import defaultdict
from datetime import datetime
import math
import uuid

from database import (
    Order, Product, BOM, MoldData, MoldCalculation,
    MoldManufacturingOrder, MoldOrderDetail
)


class MoldMOGenerator:
    """模具製令生成器"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def generate_mold_mos(self, order_ids: List[str]) -> List[MoldManufacturingOrder]:
        """
        為給定的訂單列表生成模具製令
        
        流程:
        1. 獲取訂單和其成品
        2. 通過BOM展開子件
        3. 查詢子件對應的模具
        4. 按模具分組合併需求
        5. 生成模具製令和訂單明細
        
        Args:
            order_ids: 訂單ID列表
            
        Returns:
            模具製令列表
        """
        print(f"\n=== 開始生成模具製令 ===")
        print(f"訂單數量: {len(order_ids)}")
        
        # Step 1: 收集所有訂單的子件需求
        # 結構: {mold_code: [(order_info, component_code, component_qty), ...]}
        # 改為只按模具分組，不再區分子件
        mold_demands = defaultdict(list)
        
        for order_id in order_ids:
            order = self.db.query(Order).filter(Order.id == order_id).first()
            if not order:
                print(f"⚠️  訂單 {order_id} 不存在，跳過")
                continue
            
            print(f"\n處理訂單: {order.order_number} (品號: {order.product_code})")
            
            # 獲取訂單的成品產品
            finished_product = self.db.query(Product).filter(
                Product.order_id == order_id,
                Product.product_code.like('0%'),
                Product.product_type == 'finished'
            ).first()
            
            if not finished_product:
                print(f"  ⚠️  找不到成品，跳過")
                continue
            
            # 使用 undelivered_quantity 作為需求數量
            required_qty = finished_product.undelivered_quantity or finished_product.quantity
            print(f"  成品需求: {required_qty}")
            
            # 通過BOM查找子件
            bom_items = self.db.query(BOM).filter(
                BOM.product_code == finished_product.product_code
            ).all()
            
            if not bom_items:
                print(f"  ⚠️  BOM中無子件資料，跳過")
                continue
            
            for bom in bom_items:
                component_code = bom.component_code
                
                # 查找該子件的產品記錄（獲取 undelivered_quantity）
                component_product = self.db.query(Product).filter(
                    Product.order_id == order_id,
                    Product.product_code == component_code
                ).first()
                
                if not component_product:
                    print(f"  ⚠️  子件 {component_code} 無產品記錄，跳過")
                    continue
                
                # 使用子件的 undelivered_quantity
                component_qty = component_product.undelivered_quantity or component_product.quantity
                
                # 查詢子件對應的模具
                mold_info = self._get_mold_info(component_code)
                
                if not mold_info:
                    print(f"  ⚠️  子件 {component_code} 無模具資料，跳過")
                    continue
                
                mold_code, cavity_count, machine_id = mold_info
                print(f"  子件 {component_code} → 模具 {mold_code} (穴數: {cavity_count}, 需求: {component_qty})")
                
                # 記錄需求 - 只按模具分組，不區分子件
                mold_demands[mold_code].append({
                    'order_id': order.id,
                    'order_number': order.order_number,
                    'product_code': finished_product.product_code,
                    'component_code': component_code,  # 記錄子件代碼
                    'component_qty': component_qty,
                    'due_date': order.due_date,
                    'priority': order.priority or 3,
                    'cavity_count': cavity_count,
                    'machine_id': machine_id
                })
        
        # Step 2: 為每個模具生成製令（合併所有子件）
        mold_mos = []
        
        print(f"\n=== 生成模具製令 ===")
        print(f"模具數量: {len(mold_demands)}")
        
        for mold_code, items_info in mold_demands.items():
            # 收集該模具下的所有子件
            component_codes = list(set(info['component_code'] for info in items_info))
            
            # 計算合併後的總需求（所有子件的總和）
            total_qty = sum(info['component_qty'] for info in items_info)
            cavity_count = items_info[0]['cavity_count']
            machine_id = items_info[0]['machine_id']
            
            # 計算總回次
            total_rounds = math.ceil(total_qty / cavity_count) if cavity_count > 0 else 0
            
            # 找出最早交期和最高優先級
            earliest_due = min(info['due_date'] for info in items_info)
            highest_priority = min(info['priority'] for info in items_info)  # priority 越小越高
            
            # 生成模具製令ID
            mold_mo_id = str(uuid.uuid4())
            
            # 將多個子件用逗號連接
            component_codes_str = ','.join(sorted(component_codes))
            
            print(f"\n模具製令: {mold_code}")
            print(f"  子件: {component_codes_str} ({len(component_codes)}個)")
            print(f"  總需求: {total_qty}, 總回次: {total_rounds}")
            print(f"  最早交期: {earliest_due}, 最高優先級: {highest_priority}")
            print(f"  包含項目數: {len(items_info)}（訂單×子件）")
            
            # 創建模具製令（component_code 存儲多個子件的組合）
            mold_mo = MoldManufacturingOrder(
                id=mold_mo_id,
                mold_code=mold_code,
                component_code=component_codes_str,  # 存儲所有子件，用逗號分隔
                total_quantity=total_qty,
                total_rounds=total_rounds,
                cavity_count=cavity_count,
                machine_id=machine_id,
                earliest_due_date=earliest_due,
                highest_priority=highest_priority,
                status="PENDING"
            )
            
            self.db.add(mold_mo)
            mold_mos.append(mold_mo)
            
            # 創建訂單明細（每個訂單×子件組合一筆）
            for info in items_info:
                component_rounds = math.ceil(info['component_qty'] / cavity_count) if cavity_count > 0 else 0
                
                detail = MoldOrderDetail(
                    mold_mo_id=mold_mo_id,
                    order_id=info['order_id'],
                    order_number=info['order_number'],
                    product_code=info['product_code'],
                    component_code=info['component_code'],  # 記錄具體子件
                    component_quantity=info['component_qty'],
                    component_rounds=component_rounds,
                    due_date=info['due_date'],
                    priority=info['priority']
                )
                self.db.add(detail)
                print(f"    - 訂單 {info['order_number']} × 子件 {info['component_code']}: {info['component_qty']}個 ({component_rounds}回)")
        
        self.db.commit()
        
        print(f"\n=== 生成完成 ===")
        print(f"共生成 {len(mold_mos)} 個模具製令")
        
        return mold_mos
    
    def _get_mold_info(self, component_code: str) -> Tuple[str, int, str]:
        """
        獲取子件對應的模具信息
        
        Returns:
            (mold_code, cavity_count, machine_id) 或 None
        """
        # 優先從 MoldCalculation 查詢
        mold_calc = self.db.query(MoldCalculation).filter(
            MoldCalculation.component_code == component_code
        ).first()
        
        if mold_calc and mold_calc.mold_code:
            return (
                mold_calc.mold_code,
                int(mold_calc.cavity_count) if mold_calc.cavity_count else 1,
                mold_calc.machine_id
            )
        
        # 退而求其次從 MoldData 查詢
        mold_data = self.db.query(MoldData).filter(
            MoldData.component_code == component_code
        ).first()
        
        if mold_data and mold_data.mold_code:
            return (
                mold_data.mold_code,
                int(mold_data.cavity_count) if mold_data.cavity_count else 1,
                mold_data.machine_id
            )
        
        return None
    
    def clear_mold_mos(self):
        """清空所有模具製令和明細"""
        self.db.query(MoldOrderDetail).delete()
        self.db.query(MoldManufacturingOrder).delete()
        self.db.commit()
        print("✓ 已清空所有模具製令")


# ===== 測試函數 =====

def test_generate_mold_mos():
    """測試模具製令生成"""
    from database import SessionLocal
    
    db = SessionLocal()
    try:
        generator = MoldMOGenerator(db)
        
        # 清空舊資料
        generator.clear_mold_mos()
        
        # 獲取所有訂單
        orders = db.query(Order).all()
        order_ids = [o.id for o in orders]
        
        print(f"測試訂單數: {len(order_ids)}")
        
        # 生成模具製令
        mold_mos = generator.generate_mold_mos(order_ids)
        
        # 驗證結果
        print(f"\n=== 驗證結果 ===")
        for mold_mo in mold_mos:
            details = db.query(MoldOrderDetail).filter(
                MoldOrderDetail.mold_mo_id == mold_mo.id
            ).all()
            
            print(f"\n模具製令: {mold_mo.mold_code}")
            print(f"  ID: {mold_mo.id}")
            print(f"  子件: {mold_mo.component_code}")
            print(f"  總需求: {mold_mo.total_quantity}, 總回次: {mold_mo.total_rounds}")
            print(f"  穴數: {mold_mo.cavity_count}")
            print(f"  最早交期: {mold_mo.earliest_due_date}")
            print(f"  訂單明細數: {len(details)}")
            
            total_check = sum(d.component_quantity for d in details)
            print(f"  驗證: 明細總和 {total_check} == 製令總量 {mold_mo.total_quantity} ? {total_check == mold_mo.total_quantity}")
        
    finally:
        db.close()


if __name__ == "__main__":
    test_generate_mold_mos()
