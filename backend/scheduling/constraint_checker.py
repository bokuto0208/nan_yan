"""
約束檢查器 - 檢查所有硬性限制
"""
from typing import List, Optional, Set, Tuple
from datetime import datetime, time as dt_time, timedelta
from sqlalchemy.orm import Session
from database import Downtime, WorkCalendarDay, Machine
from .models import (
    ManufacturingOrder, 
    SchedulingConfig, 
    WorkInterval,
    ScheduleBlock
)


class ConstraintChecker:
    """約束檢查器"""
    
    def __init__(self, db: Session, config: SchedulingConfig):
        self.db = db
        self.config = config
        self._work_calendar_cache = {}
    
    def get_work_intervals(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[WorkInterval]:
        """
        獲取指定日期範圍內的工作時間區間（從 WorkCalendarGap 預先計算的基礎空檔）
        
        Args:
            start_date: 開始日期
            end_date: 結束日期
            
        Returns:
            工作時間區間列表
        """
        from database import WorkCalendarGap
        
        intervals = []
        
        # 從 WorkCalendarGap 表查詢基礎空檔（已預先計算）
        gaps = self.db.query(WorkCalendarGap).filter(
            WorkCalendarGap.gap_start <= end_date,
            WorkCalendarGap.gap_end >= start_date
        ).order_by(WorkCalendarGap.gap_start).all()
        
        for gap in gaps:
            # 只保留與查詢範圍重疊的部分
            actual_start = max(gap.gap_start, start_date)
            actual_end = min(gap.gap_end, end_date)
            
            if actual_start < actual_end:
                intervals.append(WorkInterval(
                    start_time=actual_start,
                    end_time=actual_end
                ))
        
        return intervals
    
    def get_downtime_slots(
        self, 
        machine_id: str, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Tuple[datetime, datetime]]:
        """
        獲取機台的停機時段
        
        Args:
            machine_id: 機台ID
            start_date: 開始時間
            end_date: 結束時間
            
        Returns:
            停機時段列表 [(start, end), ...]
        """
        downtimes = self.db.query(Downtime).filter(
            Downtime.machine_id == machine_id,
            Downtime.date >= start_date.date().strftime('%Y-%m-%d'),
            Downtime.date <= end_date.date().strftime('%Y-%m-%d')
        ).all()
        
        slots = []
        for dt in downtimes:
            # 將 hour (小時數) 轉換為實際時間
            # 假設 start_hour=8 表示當天 08:00
            date = datetime.strptime(dt.date, '%Y-%m-%d').date()
            
            # 處理 8-32 時間軸 (8點到隔天8點)
            start_hour = int(dt.start_hour)
            end_hour = int(dt.end_hour)
            
            if start_hour < 24:
                dt_start = datetime.combine(date, dt_time(start_hour % 24, 0))
            else:
                # 跨到隔天
                dt_start = datetime.combine(date + timedelta(days=1), dt_time(start_hour % 24, 0))
            
            if end_hour < 24:
                dt_end = datetime.combine(date, dt_time(end_hour % 24, 0))
            else:
                dt_end = datetime.combine(date + timedelta(days=1), dt_time(end_hour % 24, 0))
            
            slots.append((dt_start, dt_end))
        
        return slots
    
    def check_time_overlap(
        self,
        start1: datetime,
        end1: datetime,
        start2: datetime,
        end2: datetime
    ) -> bool:
        """檢查兩個時間段是否重疊"""
        return start1 < end2 and start2 < end1
    
    def check_downtime_conflict(
        self,
        machine_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """
        檢查是否與停機時段衝突
        
        Returns:
            True: 有衝突, False: 無衝突
        """
        downtimes = self.get_downtime_slots(machine_id, start_time, end_time)
        
        for dt_start, dt_end in downtimes:
            if self.check_time_overlap(start_time, end_time, dt_start, dt_end):
                return True
        
        return False
    
    def check_changeover_forbidden_zone(
        self,
        changeover_start: datetime,
        changeover_minutes: int
    ) -> bool:
        """
        檢查換模時間是否落入禁區 (20:00-01:00)
        
        Args:
            changeover_start: 換模開始時間
            changeover_minutes: 換模時間(分鐘)
            
        Returns:
            True: 違反禁區, False: 不違反
        """
        changeover_end = changeover_start + timedelta(minutes=changeover_minutes)
        
        # 解析禁區時間
        forbidden_start_str = self.config.changeover_forbidden_start  # "20:00"
        forbidden_end_str = self.config.changeover_forbidden_end  # "01:00"
        
        forbidden_start_hour = int(forbidden_start_str.split(':')[0])
        forbidden_end_hour = int(forbidden_end_str.split(':')[0])
        
        # 建立當天和前一天的禁區時間範圍 (因為禁區跨日)
        date = changeover_start.date()
        
        # 當天的禁區: 當天20:00 ~ 隔天01:00
        forbidden_start_today = datetime.combine(date, dt_time(forbidden_start_hour, 0))
        forbidden_end_today = datetime.combine(date + timedelta(days=1), dt_time(forbidden_end_hour, 0))
        
        # 前一天的禁區: 前一天20:00 ~ 當天01:00
        forbidden_start_yesterday = datetime.combine(date - timedelta(days=1), dt_time(forbidden_start_hour, 0))
        forbidden_end_yesterday = datetime.combine(date, dt_time(forbidden_end_hour, 0))
        
        # 檢查是否與任一禁區重疊
        overlap_today = self.check_time_overlap(
            changeover_start, changeover_end,
            forbidden_start_today, forbidden_end_today
        )
        
        overlap_yesterday = self.check_time_overlap(
            changeover_start, changeover_end,
            forbidden_start_yesterday, forbidden_end_yesterday
        )
        
        return overlap_today or overlap_yesterday
    
    def check_must_end_at_shift_end(
        self,
        end_time: datetime,
        must_align: bool
    ) -> bool:
        """
        檢查是否需要對齊下班時間
        
        Args:
            end_time: 計畫結束時間
            must_align: 是否需要對齊
            
        Returns:
            True: 違反限制, False: 符合限制
        """
        if not must_align:
            return False
        
        # 解析下班時間
        shift_end_str = self.config.shift_end_time  # "01:00"
        shift_end_hour = int(shift_end_str.split(':')[0])
        
        # 檢查結束時間是否為 01:00
        if shift_end_hour < 12:
            # 隔天凌晨
            expected_time = dt_time(shift_end_hour, 0)
        else:
            expected_time = dt_time(shift_end_hour, 0)
        
        return end_time.time() != expected_time
    
    def check_mold_concurrency(
        self,
        mold_code: str,
        start_time: datetime,
        end_time: datetime,
        existing_blocks: List[ScheduleBlock],
        exclude_block_id: Optional[str] = None
    ) -> bool:
        """
        檢查模具並行限制 (同一副模具同時只能在一台機台)
        
        Args:
            mold_code: 模具編號
            start_time: 開始時間
            end_time: 結束時間
            existing_blocks: 現有排程區塊
            exclude_block_id: 排除的區塊ID (用於重排時)
            
        Returns:
            True: 違反限制 (模具已被佔用), False: 符合限制
        """
        for block in existing_blocks:
            if exclude_block_id and block.block_id == exclude_block_id:
                continue
            
            if block.mold_code == mold_code:
                # 檢查時間是否重疊
                if self.check_time_overlap(start_time, end_time, block.start_time, block.end_time):
                    return True
        
        return False
    
    def check_machine_availability(
        self,
        machine_id: str,
        start_time: datetime,
        end_time: datetime,
        existing_blocks: List[ScheduleBlock],
        exclude_block_id: Optional[str] = None
    ) -> bool:
        """
        檢查機台可用性 (同一機台同時不可重疊)
        
        Returns:
            True: 機台被佔用, False: 機台可用
        """
        for block in existing_blocks:
            if exclude_block_id and block.block_id == exclude_block_id:
                continue
            
            if block.machine_id == machine_id:
                if self.check_time_overlap(start_time, end_time, block.start_time, block.end_time):
                    return True
        
        return False
    
    def is_machine_exists(self, machine_id: str) -> bool:
        """檢查機台是否存在"""
        return self.db.query(Machine).filter(Machine.machine_id == machine_id).first() is not None
