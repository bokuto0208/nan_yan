"""
候選生成器 - Phase 2
為製令生成排程候選時段
"""
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .models import (
    ManufacturingOrder,
    MoldInfo,
    ScheduleBlock,
    SchedulingConfig,
    ScheduleCandidate
)
from .time_estimator import TimeEstimator
from .constraint_checker import ConstraintChecker
from .validator import ScheduleValidator
from .gap_calculator import GapCalculator, TimeGap


class CandidateGenerator:
    """排程候選生成器"""
    
    def __init__(
        self,
        db: Session,
        config: SchedulingConfig,
        time_estimator: TimeEstimator,
        constraint_checker: ConstraintChecker,
        validator: ScheduleValidator,
        gap_calculator: GapCalculator
    ):
        self.db = db
        self.config = config
        self.time_estimator = time_estimator
        self.constraint_checker = constraint_checker
        self.validator = validator
        self.gap_calculator = gap_calculator
        
    def generate_candidates_for_mo(
        self,
        mo: ManufacturingOrder,
        existing_blocks: List[ScheduleBlock],
        earliest_start: Optional[datetime] = None
    ) -> List[ScheduleCandidate]:
        """
        為單個製令生成所有可能的候選
        
        Args:
            mo: 製令
            existing_blocks: 現有排程區塊
            earliest_start: 最早開始時間(預設為當前時間)
            
        Returns:
            List[ScheduleCandidate]: 候選列表
        """
        candidates = []
        
        if earliest_start is None:
            earliest_start = self.config.now_datetime
        
        # 1. 獲取可用機台
        available_machines = self.time_estimator.get_available_machines(mo.component_code)
        
        if not available_machines:
            return []
        
        # 2. 對每台機台生成候選
        for machine_id in available_machines:
            machine_candidates = self._generate_candidates_for_machine(
                mo, machine_id, existing_blocks, earliest_start
            )
            candidates.extend(machine_candidates)
        
        # 3. 按優先級排序 (延遲時間、可行性)
        candidates.sort(key=lambda c: (c.lateness_hours, not c.feasible))
        
        # 4. 限制每台機台的候選數量
        if self.config.max_candidates_per_machine > 0:
            filtered_candidates = []
            machine_counts = {}
            
            for candidate in candidates:
                count = machine_counts.get(candidate.machine_id, 0)
                if count < self.config.max_candidates_per_machine:
                    filtered_candidates.append(candidate)
                    machine_counts[candidate.machine_id] = count + 1
            
            candidates = filtered_candidates
        
        return candidates
    
    def _generate_candidates_for_machine(
        self,
        mo: ManufacturingOrder,
        machine_id: str,
        existing_blocks: List[ScheduleBlock],
        earliest_start: datetime
    ) -> List[ScheduleCandidate]:
        """
        為特定機台生成候選
        
        Args:
            mo: 製令
            machine_id: 機台ID
            existing_blocks: 現有排程區塊
            earliest_start: 最早開始時間
            
        Returns:
            List[ScheduleCandidate]: 該機台的候選列表
        """
        candidates = []
        
        # 1. 獲取模具資訊
        mold_info = self.time_estimator.get_mold_info(mo.component_code, machine_id)
        if not mold_info:
            return []
        
        # 2. 計算需要的時間
        forming_hours, total_hours = self.time_estimator.calculate_total_time(
            mo, mold_info, include_changeover=True
        )
        changeover_hours = total_hours - forming_hours
        
        # 3. 計算空檔
        gaps = self.gap_calculator.calculate_machine_gaps(
            machine_id,
            earliest_start,
            mo.ship_due + timedelta(days=7),  # 延伸到交期後7天
            existing_blocks,
            min_gap_hours=total_hours  # 只考慮足夠大的空檔
        )
        
        # 4. 對每個空檔生成候選
        for gap in gaps:
            # 策略1: 從空檔開始處排程 (ASAP - As Soon As Possible)
            candidate_asap = self._create_candidate_at_time(
                mo, mold_info, machine_id, gap.start_time,
                existing_blocks, strategy="ASAP"
            )
            if candidate_asap:
                candidates.append(candidate_asap)
            
            # 策略2: 反推到交期 (JIT - Just In Time)
            if gap.end_time > mo.ship_due:
                # 從交期反推開始時間
                jit_start = mo.ship_due - timedelta(hours=total_hours)
                
                # 確保在空檔內
                if jit_start >= gap.start_time and jit_start < gap.end_time:
                    candidate_jit = self._create_candidate_at_time(
                        mo, mold_info, machine_id, jit_start,
                        existing_blocks, strategy="JIT"
                    )
                    if candidate_jit and candidate_jit.start_time != candidate_asap.start_time:
                        candidates.append(candidate_jit)
            
            # 策略3: 從空檔中點開始 (如果空檔很大)
            if gap.duration_hours > total_hours * 2:
                mid_point = gap.start_time + timedelta(hours=(gap.duration_hours - total_hours) / 2)
                candidate_mid = self._create_candidate_at_time(
                    mo, mold_info, machine_id, mid_point,
                    existing_blocks, strategy="MID"
                )
                if candidate_mid and candidate_mid not in candidates:
                    candidates.append(candidate_mid)
        
        # 5. 如果沒有找到候選，使用 EFT (Earliest Feasible Time)
        if not candidates:
            eft = self.gap_calculator.find_earliest_feasible_time(
                machine_id, total_hours, earliest_start,
                mo.ship_due + timedelta(days=7), existing_blocks
            )
            
            if eft:
                candidate_eft = self._create_candidate_at_time(
                    mo, mold_info, machine_id, eft,
                    existing_blocks, strategy="EFT"
                )
                if candidate_eft:
                    candidates.append(candidate_eft)
        
        return candidates
    
    def _create_candidate_at_time(
        self,
        mo: ManufacturingOrder,
        mold_info: MoldInfo,
        machine_id: str,
        start_time: datetime,
        existing_blocks: List[ScheduleBlock],
        strategy: str = "ASAP"
    ) -> Optional[ScheduleCandidate]:
        """
        在特定時間創建候選
        
        Args:
            mo: 製令
            mold_info: 模具資訊
            machine_id: 機台ID
            start_time: 開始時間
            existing_blocks: 現有排程區塊
            strategy: 策略名稱
            
        Returns:
            ScheduleCandidate 或 None
        """
        # 1. 計算結束時間
        end_time, forming_hours, total_hours = self.time_estimator.calculate_end_time(
            start_time, mo, mold_info, include_changeover=True
        )
        changeover_hours = total_hours - forming_hours
        
        # 2. 計算延遲
        lateness_hours, lateness_days, is_on_time = self.time_estimator.calculate_lateness(
            end_time, mo.ship_due
        )
        
        # 3. 驗證約束
        validation_result = self.validator.validate_single_schedule(
            mo, mold_info, machine_id, start_time, existing_blocks
        )
        
        # 4. 創建候選
        candidate = ScheduleCandidate(
            mo_id=mo.id,
            machine_id=machine_id,
            mold_code=mold_info.mold_code,
            start_time=start_time,
            end_time=end_time,
            forming_hours=forming_hours,
            changeover_minutes=changeover_hours * 60,  # 轉換為分鐘
            total_hours=total_hours,
            lateness_hours=lateness_hours,
            lateness_days=lateness_days,
            is_on_time=is_on_time,
            feasible=validation_result.is_valid,
            constraint_violations=[v.message for v in validation_result.violations],
            yield_rank=mold_info.yield_rank,
            frequency=mold_info.frequency
        )
        
        return candidate
    
    def generate_batch_candidates(
        self,
        mos: List[ManufacturingOrder],
        existing_blocks: List[ScheduleBlock],
        earliest_start: Optional[datetime] = None
    ) -> Dict[str, List[ScheduleCandidate]]:
        """
        批量生成候選
        
        Args:
            mos: 製令列表
            existing_blocks: 現有排程區塊
            earliest_start: 最早開始時間
            
        Returns:
            Dict[mo_id, List[ScheduleCandidate]]: 每個製令的候選列表
        """
        all_candidates = {}
        
        for mo in mos:
            candidates = self.generate_candidates_for_mo(mo, existing_blocks, earliest_start)
            all_candidates[mo.id] = candidates
        
        return all_candidates
    
    def get_candidate_summary(
        self,
        candidates: Dict[str, List[ScheduleCandidate]]
    ) -> str:
        """生成候選摘要報告"""
        lines = []
        lines.append("=" * 60)
        lines.append("候選生成摘要")
        lines.append("=" * 60)
        
        total_mos = len(candidates)
        total_candidates = sum(len(cands) for cands in candidates.values())
        feasible_count = sum(
            sum(1 for c in cands if c.feasible)
            for cands in candidates.values()
        )
        
        lines.append(f"\n製令總數: {total_mos}")
        lines.append(f"候選總數: {total_candidates}")
        lines.append(f"可行候選: {feasible_count}")
        lines.append(f"平均每製令: {total_candidates / max(total_mos, 1):.1f} 個候選")
        
        lines.append("\n" + "=" * 60)
        lines.append("詳細資訊:")
        lines.append("=" * 60)
        
        for mo_id, cands in candidates.items():
            if cands:
                lines.append(f"\n製令 {mo_id}:")
                lines.append(f"  候選數: {len(cands)}")
                feasible = [c for c in cands if c.feasible]
                lines.append(f"  可行候選: {len(feasible)}")
                
                if feasible:
                    best = min(feasible, key=lambda c: c.lateness_hours)
                    lines.append(f"  最佳候選:")
                    lines.append(f"    機台: {best.machine_id}")
                    lines.append(f"    開始: {best.start_time.strftime('%m/%d %H:%M')}")
                    lines.append(f"    延遲: {best.lateness_hours:.2f}h ({best.lateness_days:.2f}d)")
            else:
                lines.append(f"\n製令 {mo_id}: 無候選")
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)
