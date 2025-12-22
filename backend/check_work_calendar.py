from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import WorkCalendarGap
from datetime import datetime

engine = create_engine('sqlite:///./eps_system.db')
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

try:
    # 查詢前10個工作日曆空檔
    gaps = db.query(WorkCalendarGap).order_by(WorkCalendarGap.gap_start).limit(10).all()
    
    print("前10個工作日曆空檔:")
    print("=" * 100)
    
    for gap in gaps:
        gap_date = gap.gap_start.date()
        start_hour = gap.gap_start.hour + gap.gap_start.minute / 60
        end_date = gap.gap_end.date()
        end_hour = gap.gap_end.hour + gap.gap_end.minute / 60
        
        print(f"{gap.gap_start} ~ {gap.gap_end}")
        print(f"  日期: {gap_date} startHour={start_hour:.2f} | 結束: {end_date} endHour={end_hour:.2f}")
        print()
        
finally:
    db.close()
