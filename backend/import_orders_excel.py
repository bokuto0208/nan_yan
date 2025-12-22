"""
從 Excel 匯入訂單資料
"""
import openpyxl
import uuid
from datetime import datetime
from database import SessionLocal, Order, Product, BOM, ComponentSchedule, Inventory, MoldCalculation, init_db
import math

def parse_date(value):
    """解析日期格式"""
    if not value:
        return None
    
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d')
    
    # 處理字串格式
    try:
        value_str = str(value).strip()
        if not value_str or value_str == 'None':
            return None
        
        # 嘗試不同的日期格式
        for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%m/%d/%Y']:
            try:
                dt = datetime.strptime(value_str, fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        # 如果都失敗，返回當前日期
        return datetime.now().strftime('%Y-%m-%d')
    except:
        return datetime.now().strftime('%Y-%m-%d')

def import_orders_from_excel(file_path):
    """從 Excel 匯入訂單"""
    
    # 讀取 Excel
    wb = openpyxl.load_workbook(file_path)
    ws = wb.active
    
    # 初始化資料庫
    init_db()
    db = SessionLocal()
    
    try:
        imported_count = 0
        skipped_count = 0
        updated_count = 0
        
        # 讀取表頭
        headers = {}
        for col in range(1, ws.max_column + 1):
            header = ws.cell(1, col).value
            if header:
                headers[header.strip()] = col
        
        print(f"找到的欄位: {list(headers.keys())}")
        
        # 處理每一行資料（從第2行開始）
        for row in range(2, ws.max_row + 1):
            try:
                # 提取資料
                due_date = ws.cell(row, headers.get('預定到達日', 0)).value if '預定到達日' in headers else None
                order_date = ws.cell(row, headers.get('接單日期', 0)).value if '接單日期' in headers else None
                customer_id = ws.cell(row, headers.get('客戶編號', 0)).value if '客戶編號' in headers else None
                order_number = ws.cell(row, headers.get('訂單單號', 0)).value if '訂單單號' in headers else None
                order_sequence = ws.cell(row, headers.get('訂單序', 0)).value if '訂單序' in headers else None
                product_code = ws.cell(row, headers.get('品號', 0)).value if '品號' in headers else None
                quantity = ws.cell(row, headers.get('訂單數量', 0)).value if '訂單數量' in headers else None
                undelivered_qty = ws.cell(row, headers.get('未交數量', 0)).value if '未交數量' in headers else None
                
                # 必填欄位檢查
                if not order_number or not product_code:
                    skipped_count += 1
                    continue
                
                # 格式化資料
                order_number_str = str(order_number).strip()
                product_code_str = str(product_code).strip()
                customer_id_str = str(customer_id).strip() if customer_id else None
                order_sequence_str = str(order_sequence).strip() if order_sequence else None
                
                # 解析日期
                due_date_str = parse_date(due_date)
                order_date_str = parse_date(order_date)
                
                # 轉換數量
                try:
                    quantity_int = int(float(quantity)) if quantity else 0
                except (ValueError, TypeError):
                    quantity_int = 0
                
                if quantity_int <= 0:
                    skipped_count += 1
                    continue
                
                # 計算未交數量：訂單數量 - 庫存數量
                inventory_record = db.query(Inventory).filter(
                    Inventory.product_code == product_code_str
                ).first()
                
                inventory_qty = inventory_record.quantity if inventory_record else 0
                undelivered_int = max(0, quantity_int - inventory_qty)  # 不能為負數
                
                # 檢查訂單+品號組合是否已存在
                existing_order = db.query(Order).filter(
                    Order.order_number == order_number_str,
                    Order.product_code == product_code_str
                ).first()
                
                if existing_order:
                    # 更新現有訂單
                    existing_order.due_date = due_date_str or existing_order.due_date
                    existing_order.order_date = order_date_str
                    existing_order.customer_id = customer_id_str
                    existing_order.customer_name = customer_id_str or existing_order.customer_name
                    existing_order.order_sequence = order_sequence_str
                    existing_order.product_code = product_code_str
                    existing_order.quantity = quantity_int
                    existing_order.undelivered_quantity = undelivered_int
                    existing_order.updated_at = datetime.utcnow()
                    updated_count += 1
                else:
                    # 創建新訂單
                    order_id = str(uuid.uuid4())
                    new_order = Order(
                        id=order_id,
                        order_number=order_number_str,
                        customer_name=customer_id_str or "未知客戶",
                        customer_id=customer_id_str,
                        product_code=product_code_str,
                        quantity=quantity_int,
                        undelivered_quantity=undelivered_int,
                        due_date=due_date_str or datetime.now().strftime('%Y-%m-%d'),
                        order_date=order_date_str,
                        order_sequence=order_sequence_str,
                        priority=3,
                        status="PENDING"
                    )
                    db.add(new_order)
                    db.flush()
                    
                    # 創建產品記錄（0階成品）
                    product = Product(
                        id=str(uuid.uuid4()),
                        order_id=order_id,
                        product_code=product_code_str,
                        quantity=quantity_int,
                        undelivered_quantity=undelivered_int,
                        product_type='finished'  # 0階成品
                    )
                    db.add(product)
                    db.flush()
                    
                    # 自動拆解成子件
                    bom_items = db.query(BOM).filter(BOM.product_code == product_code_str).all()
                    
                    if bom_items:
                        for bom_item in bom_items:
                            # 數量計算：未交數量 / 穴數（無條件進位）
                            required_quantity = math.ceil(undelivered_int / bom_item.cavity_count)
                            
                            # 創建1階子件產品記錄
                            component_product = Product(
                                id=str(uuid.uuid4()),
                                order_id=order_id,
                                product_code=bom_item.component_code,
                                quantity=required_quantity,
                                undelivered_quantity=required_quantity,
                                product_type='component'  # 1階子件
                            )
                            db.add(component_product)
                            
                            # 判斷初始狀態
                            if bom_item.component_code.startswith('6'):
                                initial_status = "模具"  # 6開頭是模具,不需排程
                            elif required_quantity == 0:
                                initial_status = "無法進行排程"  # 數量為0不排程
                            else:
                                # 檢查是否有完整的 mold_calculations 資料
                                # 必須有機台、穴數>0、成型時間>0
                                has_complete_mold_calc = db.query(MoldCalculation).filter(
                                    MoldCalculation.component_code == bom_item.component_code,
                                    MoldCalculation.machine_id.isnot(None),
                                    MoldCalculation.cavity_count.isnot(None),
                                    MoldCalculation.cavity_count > 0,
                                    MoldCalculation.avg_molding_time_sec.isnot(None),
                                    MoldCalculation.avg_molding_time_sec > 0
                                ).first() is not None
                                
                                if has_complete_mold_calc:
                                    initial_status = "未排程"  # 有完整資料可排程
                                else:
                                    initial_status = "無法進行排程"  # 沒有完整的模具計算資料
                            
                            # 創建元件排程記錄
                            component_schedule = ComponentSchedule(
                                id=str(uuid.uuid4()),
                                order_id=order_id,
                                component_code=bom_item.component_code,
                                quantity=required_quantity,
                                status=initial_status
                            )
                            db.add(component_schedule)
                    
                    imported_count += 1
                
                # 每100筆提交一次
                if (imported_count + updated_count) % 100 == 0:
                    db.commit()
                    print(f"已處理 {imported_count + updated_count} 筆...")
                
            except Exception as e:
                import traceback
                print(f"處理第 {row} 行時出錯: {e}")
                print(f"  訂單號: {order_number}, 品號: {product_code}")
                traceback.print_exc()
                skipped_count += 1
                continue
        
        # 最後提交
        db.commit()
        
        print("\n" + "="*60)
        print(f"✓ 匯入完成！")
        print(f"  新增: {imported_count} 筆")
        print(f"  更新: {updated_count} 筆")
        print(f"  跳過: {skipped_count} 筆")
        print("="*60)
        
        # 自動觸發模具計算
        calc_warnings = []
        try:
            print("\n正在計算模具需求...")
            from mold_calc import calculate_and_save
            import traceback
            calc_result = calculate_and_save(silent=True, save_excel=False)
            if calc_result.get('success'):
                print(f"✓ 模具計算完成：{calc_result.get('count', 0)} 筆資料已更新")
                calc_warnings = calc_result.get('warnings', [])
                if calc_warnings:
                    print("\n⚠️  警示訊息:")
                    for warning in calc_warnings:
                        print(f"  {warning}")
            else:
                print(f"⚠️  模具計算返回失敗: {calc_result}")
        except Exception as e:
            print(f"⚠️  模具計算失敗（不影響訂單匯入）: {e}")
            traceback.print_exc()
        
        return {
            "success": True,
            "imported": imported_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "warnings": calc_warnings
        }
        
    except Exception as e:
        db.rollback()
        print(f"❌ 匯入過程中發生錯誤: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    # 測試匯入
    import_orders_from_excel("raw_data/未交訂單EX.xlsx")
