from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import DailyScheduleBlock, ComponentSchedule, Order
from datetime import datetime

engine = create_engine('sqlite:///./eps_system.db')
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

try:
    # 查詢 2025-12-23 04:14 開始的區塊
    blocks = db.query(DailyScheduleBlock).filter(
        DailyScheduleBlock.scheduled_date == '2025-12-23'
    ).all()
    
    problem_blocks = []
    for block in blocks:
        base_date = datetime.strptime(block.scheduled_date, "%Y-%m-%d")
        start_diff = block.start_time - base_date
        start_hour = start_diff.total_seconds() / 3600
        
        if 0 < start_hour < 8:
            comp = db.query(ComponentSchedule).filter_by(id=block.order_id).first()
            order = db.query(Order).filter_by(id=comp.order_id).first() if comp else None
            
            problem_blocks.append({
                'id': block.id,
                'component': block.component_code,
                'machine': block.machine_id,
                'start_time': block.start_time,
                'start_hour': start_hour,
                'sequence': f"{block.sequence}/{block.total_sequences}",
                'order': order.order_number if order else 'N/A'
            })
    
    print(f"2025-12-23 有 {len(problem_blocks)} 個在8:00前開始的區塊:\n")
    for b in sorted(problem_blocks, key=lambda x: x['start_hour']):
        print(f"ID: {b['id']:5d} | {b['component']:20s} | {b['machine']:6s} | {b['start_time']} | startHour={b['start_hour']:.2f} | seq={b['sequence']}")
        
        # 檢查該訂單的所有區塊
        print(f"  訂單: {b['order']}")
        all_blocks = db.query(DailyScheduleBlock).filter_by(order_id=block.order_id).order_by(DailyScheduleBlock.start_time).all()
        if len(all_blocks) > 1:
            print(f"  這是分段區塊，所有段:")
            for ab in all_blocks:
                print(f"    {ab.scheduled_date} {ab.start_time} ~ {ab.end_time} (seq {ab.sequence}/{ab.total_sequences})")
        print()
        
finally:
    db.close()
