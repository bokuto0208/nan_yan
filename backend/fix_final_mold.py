#!/usr/bin/env python3
"""
最終修正：模具未交數量 = 同order_id的1開頭子件未交數量 / 模具穴數
"""
from database import SessionLocal, Product, BOM, MoldCalculation
import math

def fix_final_mold_quantities():
    db = SessionLocal()
    
    try:
        print('=== 最終修正模具未交數量 ===')
        print('公式：模具未交數量 = 同order_id的1開頭子件未交數量 / 模具穴數')
        
        # 找出所有模具子件（6開頭）
        mold_products = db.query(Product).filter(
            Product.product_code.like('6%'),
            Product.product_type == 'component'
        ).all()
        
        updated_count = 0
        
        for mold_product in mold_products:
            # 找同order_id的1開頭子件
            component_1_products = db.query(Product).filter(
                Product.order_id == mold_product.order_id,
                Product.product_code.like('1%'),
                Product.product_type == 'component'
            ).all()
            
            if not component_1_products:
                continue
            
            # 取第一個1開頭子件的未交數量作為基準
            base_undelivered = component_1_products[0].undelivered_quantity
            
            # 從BOM表查詢該模具的穴數
            bom = db.query(BOM).filter(BOM.component_code == mold_product.product_code).first()
            
            if not bom:
                continue
            
            # 查詢穴數（先查MoldCalculation）
            mold_calc = db.query(MoldCalculation).filter(
                MoldCalculation.component_code == mold_product.product_code
            ).first()
            
            if not mold_calc:
                mold_calc = db.query(MoldCalculation).filter(
                    MoldCalculation.mold_code == mold_product.product_code
                ).first()
            
            cavity_count = mold_calc.cavity_count if mold_calc and mold_calc.cavity_count else 1
            
            # 計算正確的模具未交數量：1開頭子件未交數量 / 模具穴數
            if base_undelivered > 0 and cavity_count > 0:
                correct_undelivered = math.ceil(base_undelivered / cavity_count)
            else:
                correct_undelivered = 0
            
            # 模具總量也需要同步調整
            if component_1_products[0].quantity > 0 and cavity_count > 0:
                correct_quantity = math.ceil(component_1_products[0].quantity / cavity_count)
            else:
                correct_quantity = 0
            
            if (mold_product.undelivered_quantity != correct_undelivered or 
                mold_product.quantity != correct_quantity):
                
                old_quantity = mold_product.quantity
                old_undelivered = mold_product.undelivered_quantity
                
                mold_product.quantity = correct_quantity
                mold_product.undelivered_quantity = correct_undelivered
                updated_count += 1
                
                print(f'模具 {mold_product.product_code} (訂單 {mold_product.order_id[:8]}...):')
                print(f'  1開頭子件未交量: {base_undelivered}, 穴數: {cavity_count}')
                print(f'  數量: {old_quantity} → {correct_quantity}')
                print(f'  未交量: {old_undelivered} → {correct_undelivered}')
                print(f'  計算: ceil({base_undelivered}/{cavity_count}) = {correct_undelivered}')
                print()
        
        db.commit()
        print(f'✓ 成功修正了 {updated_count} 筆模具記錄')
        
    except Exception as e:
        db.rollback()
        print(f'❌ 修正過程中出錯: {e}')
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == '__main__':
    fix_final_mold_quantities()