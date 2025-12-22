"""
區塊分割器 - 將跨日區塊分割成每日獨立區塊
"""
from typing import List
from datetime import datetime
from sqlalchemy.orm import Session

from .models import ScheduleBlock, SchedulingConfig, MOStatus
from .constraint_checker import ConstraintChecker


class BlockSplitter:
    """區塊分割器"""
    
    def __init__(self, db: Session, config: SchedulingConfig, constraint_checker: ConstraintChecker):
        self.db = db
        self.config = config
        self.constraint_checker = constraint_checker
    
    def split_blocks_by_workday(self, blocks: List[ScheduleBlock]) -> List[ScheduleBlock]:
        """
        將跨日區塊分割成每日獨立區塊
        
        Args:
            blocks: 原始區塊列表
            
        Returns:
            分割後的區塊列表
        """
        split_blocks = []
        
        for block in blocks:
            # 獲取該區塊時間範圍內的工作區間
            work_intervals = self.constraint_checker.get_work_intervals(
                block.start_time,
                block.end_time
            )
            
            if not work_intervals or len(work_intervals) <= 1:
                # 沒有工作區間或只在一個工作區間內，不需要分割
                split_blocks.append(block)
                continue
            
            # 記錄有效的工作區間
            valid_intervals = []
            for interval in work_intervals:
                sub_start = max(block.start_time, interval.start_time)
                sub_end = min(block.end_time, interval.end_time)
                if sub_start < sub_end:
                    valid_intervals.append((interval, sub_start, sub_end))
            
            # 按工作區間分割，並按時間順序排序確保正確編號
            # 先按開始時間排序
            valid_intervals_sorted = sorted(valid_intervals, key=lambda x: x[1])  # x[1] 是 sub_start
            total_parts = len(valid_intervals_sorted)
            
            for i, (interval, sub_start, sub_end) in enumerate(valid_intervals_sorted):
                # 創建子區塊
                sub_block = ScheduleBlock(
                    block_id=f"{block.block_id}-{i+1}",  # 添加序號
                    machine_id=block.machine_id,
                    mold_code=block.mold_code,
                    start_time=sub_start,
                    end_time=sub_end,
                    mo_ids=block.mo_ids.copy(),
                    component_codes=block.component_codes.copy(),
                    product_display=block.product_display,
                    status=block.status,
                    is_merged=block.is_merged,
                    is_locked=block.is_locked,
                    must_end_at_shift_end=True,  # 標記為必須在下班結束
                    has_changeover=(i == 0 and block.has_changeover),  # 只有第一個子區塊有換模
                    split_part=i + 1,  # 分割部分編號（1, 2, 3...）- 按時間順序
                    total_splits=total_parts  # 總共分割成幾段
                )
                
                split_blocks.append(sub_block)
        
        return split_blocks
