"""
工作日曆基礎空檔生成器
在工作日曆變更時自動生成基礎空檔資料
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import WorkCalendarDay, WorkCalendarGap


def generate_gaps_for_date(db: Session, work_date: str) -> int:
    """
    為單個日期生成基礎空檔
    
    Args:
        db: 資料庫會話
        work_date: 工作日期 'YYYY-MM-DD'
        
    Returns:
        int: 生成的空檔數量
    """
    # 查詢該日期的工作日曆
    calendar_day = db.query(WorkCalendarDay).filter(
        WorkCalendarDay.work_date == work_date
    ).first()
    
    if not calendar_day:
        return 0
    
    # 刪除該日期的舊空檔
    db.query(WorkCalendarGap).filter(
        WorkCalendarGap.work_date == work_date
    ).delete(synchronize_session=False)
    
    # 如果工作時數為 0（假日/休息日），不生成空檔
    if calendar_day.work_hours <= 0:
        db.commit()
        return 0
    
    # 解析開始時間
    try:
        start_hour, start_minute = map(int, calendar_day.start_time.split(':'))
    except:
        start_hour, start_minute = 8, 0  # 默認 08:00
    
    # 建立該日期的開始時間
    date_obj = datetime.strptime(work_date, '%Y-%m-%d')
    gap_start = date_obj.replace(hour=start_hour, minute=start_minute, second=0)
    
    # 計算結束時間（工作時數 + 1 小時員工休息時間）
    total_hours = calendar_day.work_hours + 1
    gap_end = gap_start + timedelta(hours=total_hours)
    
    # 創建基礎空檔
    gap = WorkCalendarGap(
        work_date=work_date,
        gap_start=gap_start,
        gap_end=gap_end,
        duration_hours=calendar_day.work_hours + 1  # 包含員工休息時間
    )
    
    db.add(gap)
    db.commit()
    
    return 1


def generate_gaps_for_date_range(db: Session, start_date: str, end_date: str) -> int:
    """
    為日期範圍生成基礎空檔
    
    Args:
        db: 資料庫會話
        start_date: 開始日期 'YYYY-MM-DD'
        end_date: 結束日期 'YYYY-MM-DD'
        
    Returns:
        int: 生成的空檔數量
    """
    # 查詢日期範圍內的所有工作日曆
    calendar_days = db.query(WorkCalendarDay).filter(
        WorkCalendarDay.work_date >= start_date,
        WorkCalendarDay.work_date <= end_date
    ).all()
    
    # 刪除該範圍的舊空檔
    db.query(WorkCalendarGap).filter(
        WorkCalendarGap.work_date >= start_date,
        WorkCalendarGap.work_date <= end_date
    ).delete(synchronize_session=False)
    
    count = 0
    
    for calendar_day in calendar_days:
        # 跳過假日/休息日
        if calendar_day.work_hours <= 0:
            continue
        
        # 解析開始時間
        try:
            start_hour, start_minute = map(int, calendar_day.start_time.split(':'))
        except:
            start_hour, start_minute = 8, 0
        
        # 建立該日期的開始時間
        date_obj = datetime.strptime(calendar_day.work_date, '%Y-%m-%d')
        gap_start = date_obj.replace(hour=start_hour, minute=start_minute, second=0)
        
        # 計算結束時間（工作時數 + 1 小時員工休息時間）
        total_hours = calendar_day.work_hours + 1
        gap_end = gap_start + timedelta(hours=total_hours)
        
        # 創建基礎空檔
        gap = WorkCalendarGap(
            work_date=calendar_day.work_date,
            gap_start=gap_start,
            gap_end=gap_end,
            duration_hours=calendar_day.work_hours + 1
        )
        
        db.add(gap)
        count += 1
    
    db.commit()
    
    return count


def rebuild_all_gaps(db: Session) -> int:
    """
    重建所有工作日曆的基礎空檔
    
    Args:
        db: 資料庫會話
        
    Returns:
        int: 生成的空檔數量
    """
    # 刪除所有舊空檔
    db.query(WorkCalendarGap).delete(synchronize_session=False)
    
    # 查詢所有工作日曆
    calendar_days = db.query(WorkCalendarDay).all()
    
    count = 0
    
    for calendar_day in calendar_days:
        # 跳過假日/休息日
        if calendar_day.work_hours <= 0:
            continue
        
        # 解析開始時間
        try:
            start_hour, start_minute = map(int, calendar_day.start_time.split(':'))
        except:
            start_hour, start_minute = 8, 0
        
        # 建立該日期的開始時間
        date_obj = datetime.strptime(calendar_day.work_date, '%Y-%m-%d')
        gap_start = date_obj.replace(hour=start_hour, minute=start_minute, second=0)
        
        # 計算結束時間（工作時數 + 1 小時員工休息時間）
        total_hours = calendar_day.work_hours + 1
        gap_end = gap_start + timedelta(hours=total_hours)
        
        # 創建基礎空檔
        gap = WorkCalendarGap(
            work_date=calendar_day.work_date,
            gap_start=gap_start,
            gap_end=gap_end,
            duration_hours=calendar_day.work_hours + 1
        )
        
        db.add(gap)
        count += 1
    
    db.commit()
    
    return count
