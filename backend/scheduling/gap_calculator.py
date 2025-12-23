"""
空檔計算器 - Phase 2
計算機台排程的時間空檔，考慮工時日曆和停機時段
"""
from typing import List, Tuple, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .models import ScheduleBlock, WorkInterval, SchedulingConfig
from .constraint_checker import ConstraintChecker


class TimeGap:
    """時間空檔"""
    
    def __init__(
        self,
        machine_id: str,
        start_time: datetime,
        end_time: datetime,
        duration_hours: float,
        is_work_time: bool = True,
        has_downtime: bool = False
    ):
        self.machine_id = machine_id
        self.start_time = start_time
        self.end_time = end_time
        self.duration_hours = duration_hours
        self.is_work_time = is_work_time
        self.has_downtime = has_downtime
        
    def __repr__(self):
        return (f"TimeGap(machine={self.machine_id}, "
                f"{self.start_time.strftime('%m/%d %H:%M')} ~ "
                f"{self.end_time.strftime('%m/%d %H:%M')}, "
                f"{self.duration_hours:.2f}h)")
    
    def to_dict(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_hours": self.duration_hours,
            "is_work_time": self.is_work_time,
            "has_downtime": self.has_downtime
        }


class GapCalculator:
    """空檔計算器"""
    
    def __init__(
        self,
        db: Session,
        config: SchedulingConfig,
        constraint_checker: ConstraintChecker
    ):
        self.db = db
        self.config = config
        self.constraint_checker = constraint_checker
    
    def _ensure_work_start_time(self, time: datetime) -> datetime:
        """確保時間不早於當天的工作開始時間(8:00)"""
        work_start_hour = 8
        # 獲取該時間所在日期的8:00
        day_start = datetime(time.year, time.month, time.day, work_start_hour, 0, 0)
        # 如果時間早於8:00，則調整到8:00
        if time < day_start:
            return day_start
        return time
        
    def calculate_machine_gaps(
        self,
        machine_id: str,
        start_date: datetime,
        end_date: datetime,
        existing_blocks: List[ScheduleBlock],
        min_gap_hours: float = 0.5
    ) -> List[TimeGap]:
        """
        計算單台機台的時間空檔
        
        Args:
            machine_id: 機台ID
            start_date: 開始日期
            end_date: 結束日期
            existing_blocks: 現有排程區塊
            min_gap_hours: 最小空檔時間(小時)
            
        Returns:
            List[TimeGap]: 時間空檔列表
        """
        gaps = []
        
        # 1. 獲取該機台的現有排程，按開始時間排序
        machine_blocks = sorted(
            [b for b in existing_blocks if b.machine_id == machine_id],
            key=lambda x: x.start_time
        )
        
        # 2. 獲取工時日曆
        work_intervals = self.constraint_checker.get_work_intervals(start_date, end_date)
        
        if not work_intervals:
            # 如果沒有工時日曆，使用連續時間
            work_intervals = [WorkInterval(start_time=start_date, end_time=end_date)]
        
        # 3. 合併連續的工作區間（機台可以跨天連續生產）
        # 將工作區間視為整體可用時間，只在有排程區塊的地方分割
        
        if not machine_blocks:
            # 沒有現有排程，整個時間範圍都是空檔
            if work_intervals:
                # 確保開始時間不早於當天8:00
                gap_start = self._ensure_work_start_time(work_intervals[0].start_time)
                gap_end = work_intervals[-1].end_time
                
                # 按停機時間分割空檔
                sub_gaps = self._split_gap_by_downtime(
                    machine_id, gap_start, gap_end, work_intervals, min_gap_hours
                )
                gaps.extend(sub_gaps)
        else:
            # 有現有排程，計算排程區塊之間的空檔
            # 使用工作區間的總時長來計算
            
            # 第一個空檔：從第一個工作區間開始到第一個排程區塊
            first_block = machine_blocks[0]
            first_work_start = work_intervals[0].start_time if work_intervals else start_date
            
            if first_block.start_time > first_work_start:
                gap_start = max(first_work_start, start_date)
                # 確保空檔開始時間不早於當天8:00
                gap_start = self._ensure_work_start_time(gap_start)
                gap_end = first_block.start_time
                
                # 按停機時間分割空檔
                sub_gaps = self._split_gap_by_downtime(
                    machine_id, gap_start, gap_end, work_intervals, min_gap_hours
                )
                gaps.extend(sub_gaps)
            
            # 中間的空檔：排程區塊之間
            for i in range(len(machine_blocks) - 1):
                current_block = machine_blocks[i]
                next_block = machine_blocks[i + 1]
                
                gap_start = current_block.end_time
                # 確保空檔開始時間不早於當天8:00
                gap_start = self._ensure_work_start_time(gap_start)
                gap_end = next_block.start_time
                
                if gap_end > gap_start:
                    # 按停機時間分割空檔
                    sub_gaps = self._split_gap_by_downtime(
                        machine_id, gap_start, gap_end, work_intervals, min_gap_hours
                    )
                    gaps.extend(sub_gaps)
            
            # 最後一個空檔：最後一個排程區塊到最後一個工作區間結束
            last_block = machine_blocks[-1]
            last_work_end = work_intervals[-1].end_time if work_intervals else end_date
            
            if last_block.end_time < last_work_end:
                gap_start = last_block.end_time
                # 確保空檔開始時間不早於當天8:00
                gap_start = self._ensure_work_start_time(gap_start)
                gap_end = min(last_work_end, end_date)
                
                # 按停機時間分割空檔
                sub_gaps = self._split_gap_by_downtime(
                    machine_id, gap_start, gap_end, work_intervals, min_gap_hours
                )
                gaps.extend(sub_gaps)
        
        return gaps
    
    def _calculate_work_duration_between(
        self, 
        start_time: datetime, 
        end_time: datetime, 
        work_intervals: List[WorkInterval]
    ) -> float:
        """
        計算指定時間範圍內的實際工作時長（小時）
        
        Args:
            start_time: 開始時間
            end_time: 結束時間
            work_intervals: 工作時間區間列表
            
        Returns:
            float: 工作時長（小時）
        """
        total_duration = 0.0
        
        for interval in work_intervals:
            # 計算重疊部分
            overlap_start = max(start_time, interval.start_time)
            overlap_end = min(end_time, interval.end_time)
            
            if overlap_start < overlap_end:
                duration = (overlap_end - overlap_start).total_seconds() / 3600
                total_duration += duration
        
        return total_duration
    
    def calculate_all_machines_gaps(
        self,
        machine_ids: List[str],
        start_date: datetime,
        end_date: datetime,
        existing_blocks: List[ScheduleBlock],
        min_gap_hours: float = 0.5
    ) -> dict:
        """
        計算所有機台的空檔
        
        Returns:
            Dict[machine_id, List[TimeGap]]: 每台機台的空檔列表
        """
        all_gaps = {}
        
        for machine_id in machine_ids:
            gaps = self.calculate_machine_gaps(
                machine_id, start_date, end_date, existing_blocks, min_gap_hours
            )
            all_gaps[machine_id] = gaps
        
        return all_gaps
    
    def find_earliest_feasible_time(
        self,
        machine_id: str,
        required_hours: float,
        earliest_start: datetime,
        latest_end: datetime,
        existing_blocks: List[ScheduleBlock]
    ) -> Optional[datetime]:
        """
        找到最早可行時間 (EFT - Earliest Feasible Time)
        
        Args:
            machine_id: 機台ID
            required_hours: 需要的時間(小時)
            earliest_start: 最早開始時間
            latest_end: 最晚結束時間(交期)
            existing_blocks: 現有排程區塊
            
        Returns:
            datetime: 最早可行的開始時間，如果找不到則返回 None
        """
        # 計算空檔
        gaps = self.calculate_machine_gaps(
            machine_id,
            earliest_start,
            latest_end,
            existing_blocks,
            min_gap_hours=0  # 不限制最小空檔
        )
        
        # 遍歷空檔，找到第一個足夠大的
        for gap in gaps:
            if gap.start_time >= earliest_start and gap.duration_hours >= required_hours:
                # 檢查是否有停機
                if not gap.has_downtime:
                    return gap.start_time
                else:
                    # 如果有停機，嘗試停機後的時間
                    downtimes = self.constraint_checker.get_downtime_slots(
                        machine_id, gap.start_time, gap.end_time
                    )
                    
                    # 找到停機後的第一個可用時間
                    candidate_start = gap.start_time
                    for dt_start, dt_end in downtimes:
                        if dt_start <= candidate_start:
                            candidate_start = max(candidate_start, dt_end)
                    
                    # 檢查剩餘時間是否足夠
                    remaining_hours = (gap.end_time - candidate_start).total_seconds() / 3600
                    if remaining_hours >= required_hours:
                        return candidate_start
        
        return None
    
    def _blocks_overlap(
        self,
        start1: datetime,
        end1: datetime,
        start2: datetime,
        end2: datetime
    ) -> bool:
        """檢查兩個時間段是否重疊"""
        return start1 < end2 and start2 < end1
    
    def _has_downtime(
        self,
        machine_id: str,
        start_time: datetime,
        end_time: datetime
    ) -> bool:
        """檢查時間段內是否有停機"""
        downtimes = self.constraint_checker.get_downtime_slots(
            machine_id, start_time, end_time
        )
        return len(downtimes) > 0    
    def _split_gap_by_downtime(
        self,
        machine_id: str,
        gap_start: datetime,
        gap_end: datetime,
        work_intervals: List[WorkInterval],
        min_gap_hours: float
    ) -> List[TimeGap]:
        """
        將空檔按停機時間分割成多個子空檔
        
        Args:
            machine_id: 機台ID
            gap_start: 空檔開始時間
            gap_end: 空檔結束時間
            work_intervals: 工作區間列表
            min_gap_hours: 最小空檔時長
            
        Returns:
            List[TimeGap]: 分割後的空檔列表（排除停機時段）
        """
        # 獲取這段時間內的停機時段 (返回 List[Tuple[datetime, datetime]])
        downtimes = self.constraint_checker.get_downtime_slots(
            machine_id, gap_start, gap_end
        )
        
        if not downtimes:
            # 沒有停機，返回完整空檔
            duration = self._calculate_work_duration_between(gap_start, gap_end, work_intervals)
            if duration >= min_gap_hours:
                return [TimeGap(
                    machine_id=machine_id,
                    start_time=gap_start,
                    end_time=gap_end,
                    duration_hours=duration,
                    is_work_time=True,
                    has_downtime=False
                )]
            return []
        
        # 有停機，按停機時段分割
        gaps = []
        current_start = gap_start
        
        # 按開始時間排序停機時段 (tuple 的第一個元素是開始時間)
        sorted_downtimes = sorted(downtimes, key=lambda d: d[0])
        
        for dt_start, dt_end in sorted_downtimes:
            # 停機前的空檔
            if current_start < dt_start:
                duration = self._calculate_work_duration_between(current_start, dt_start, work_intervals)
                if duration >= min_gap_hours:
                    gaps.append(TimeGap(
                        machine_id=machine_id,
                        start_time=current_start,
                        end_time=dt_start,
                        duration_hours=duration,
                        is_work_time=True,
                        has_downtime=False
                    ))
            
            # 跳過停機時段
            current_start = max(current_start, dt_end)
        
        # 最後一個停機後的空檔
        if current_start < gap_end:
            duration = self._calculate_work_duration_between(current_start, gap_end, work_intervals)
            if duration >= min_gap_hours:
                gaps.append(TimeGap(
                    machine_id=machine_id,
                    start_time=current_start,
                    end_time=gap_end,
                    duration_hours=duration,
                    is_work_time=True,
                    has_downtime=False
                ))
        
        return gaps
