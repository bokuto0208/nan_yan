"""
订单合并优化器 - Phase 4
实现交期窗口内的订单合并逻辑
"""
from typing import List, Optional, Dict, Tuple, Set
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .models import (
    ManufacturingOrder,
    MoldInfo,
    ScheduleBlock,
    SchedulingConfig,
    ScheduleCandidate,
    MergeStrategy
)
from .time_estimator import TimeEstimator
from .constraint_checker import ConstraintChecker
from .validator import ScheduleValidator


class MergeGroup:
    """可合并的订单组"""
    
    def __init__(
        self,
        component_code: str,
        machine_id: str,
        mold_code: str,
        mos: List[ManufacturingOrder]
    ):
        self.component_code = component_code
        self.machine_id = machine_id
        self.mold_code = mold_code
        self.mos = mos
        self.total_quantity = sum(mo.quantity for mo in mos)
        self.earliest_due = min(mo.ship_due for mo in mos)
        self.latest_due = max(mo.ship_due for mo in mos)
        
    def __repr__(self):
        return (f"MergeGroup({self.component_code}, {self.machine_id}, "
                f"{len(self.mos)} orders, {self.total_quantity} units)")
    
    def to_dict(self) -> dict:
        return {
            "component_code": self.component_code,
            "machine_id": self.machine_id,
            "mold_code": self.mold_code,
            "mo_count": len(self.mos),
            "mo_ids": [mo.id for mo in self.mos],
            "total_quantity": self.total_quantity,
            "earliest_due": self.earliest_due.isoformat(),
            "latest_due": self.latest_due.isoformat()
        }


class MergeEvaluation:
    """合并评估结果"""
    
    def __init__(
        self,
        merge_group: MergeGroup,
        is_feasible: bool,
        total_hours: float,
        forming_hours: float,
        changeover_hours: float,
        saved_changeover_hours: float,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        constraint_violations: List[str] = None
    ):
        self.merge_group = merge_group
        self.is_feasible = is_feasible
        self.total_hours = total_hours
        self.forming_hours = forming_hours
        self.changeover_hours = changeover_hours
        self.saved_changeover_hours = saved_changeover_hours
        self.start_time = start_time
        self.end_time = end_time
        self.constraint_violations = constraint_violations or []
        
    def to_dict(self) -> dict:
        return {
            "merge_group": self.merge_group.to_dict(),
            "is_feasible": self.is_feasible,
            "total_hours": self.total_hours,
            "forming_hours": self.forming_hours,
            "changeover_hours": self.changeover_hours,
            "saved_changeover_hours": self.saved_changeover_hours,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "constraint_violations": self.constraint_violations
        }


class OrderMerger:
    """订单合并器"""
    
    def __init__(
        self,
        db: Session,
        config: SchedulingConfig,
        time_estimator: TimeEstimator,
        constraint_checker: ConstraintChecker,
        validator: ScheduleValidator
    ):
        self.db = db
        self.config = config
        self.time_estimator = time_estimator
        self.constraint_checker = constraint_checker
        self.validator = validator
        
    def identify_merge_opportunities(
        self,
        mos: List[ManufacturingOrder],
        selected_candidates: Dict[str, ScheduleCandidate]
    ) -> List[MergeGroup]:
        """
        识别可合并的订单组
        
        Args:
            mos: 制令列表
            selected_candidates: 已选择的候选 {mo_id: candidate}
            
        Returns:
            List[MergeGroup]: 可合并组列表
        """
        if not self.config.merge_enabled:
            return []
        
        # 按 (component_code, machine_id) 分组
        groups: Dict[Tuple[str, str], List[ManufacturingOrder]] = {}
        
        for mo in mos:
            if mo.id not in selected_candidates:
                continue
            
            candidate = selected_candidates[mo.id]
            key = (mo.component_code, candidate.machine_id)
            
            if key not in groups:
                groups[key] = []
            groups[key].append(mo)
        
        # 过滤出可合并的组（至少2个订单）
        merge_groups = []
        
        for (component_code, machine_id), group_mos in groups.items():
            if len(group_mos) < 2:
                continue
            
            # 检查交期窗口
            if self.config.merge_strategy == MergeStrategy.MERGE_WITHIN_DEADLINE:
                filtered_mos = self._filter_by_deadline_window(group_mos)
                
                if len(filtered_mos) >= 2:
                    # 获取模具信息
                    mold_info = self.time_estimator.get_mold_info(component_code, machine_id)
                    if mold_info:
                        merge_groups.append(MergeGroup(
                            component_code=component_code,
                            machine_id=machine_id,
                            mold_code=mold_info.mold_code,
                            mos=filtered_mos
                        ))
        
        return merge_groups
    
    def _filter_by_deadline_window(
        self,
        mos: List[ManufacturingOrder]
    ) -> List[ManufacturingOrder]:
        """
        根据交期窗口过滤订单
        
        Args:
            mos: 制令列表
            
        Returns:
            在窗口内的制令列表
        """
        if len(mos) < 2:
            return mos
        
        # 按交期排序
        sorted_mos = sorted(mos, key=lambda mo: mo.ship_due)
        
        # 计算窗口大小
        window_days = self.config.merge_window_weeks * 7
        
        # 找出最大可合并组
        best_group = []
        
        for i in range(len(sorted_mos)):
            current_group = [sorted_mos[i]]
            earliest_due = sorted_mos[i].ship_due
            
            for j in range(i + 1, len(sorted_mos)):
                days_diff = (sorted_mos[j].ship_due - earliest_due).days
                
                if days_diff <= window_days:
                    current_group.append(sorted_mos[j])
            
            if len(current_group) > len(best_group):
                best_group = current_group
        
        return best_group
    
    def evaluate_merge(
        self,
        merge_group: MergeGroup,
        existing_blocks: List[ScheduleBlock],
        earliest_start: Optional[datetime] = None
    ) -> MergeEvaluation:
        """
        评估合并可行性
        
        Args:
            merge_group: 合并组
            existing_blocks: 现有排程区块
            earliest_start: 最早开始时间
            
        Returns:
            MergeEvaluation: 评估结果
        """
        if earliest_start is None:
            earliest_start = self.config.now_datetime
        
        # 获取模具信息
        mold_info = self.time_estimator.get_mold_info(
            merge_group.component_code,
            merge_group.machine_id
        )
        
        if not mold_info:
            return MergeEvaluation(
                merge_group=merge_group,
                is_feasible=False,
                total_hours=0,
                forming_hours=0,
                changeover_hours=0,
                saved_changeover_hours=0,
                constraint_violations=["找不到模具信息"]
            )
        
        # 计算合并后的总时间
        total_quantity = merge_group.total_quantity
        
        # 创建虚拟制令用于计算
        merged_mo = ManufacturingOrder(
            id="MERGED",
            order_id="MERGED",
            component_code=merge_group.component_code,
            product_code="MERGED",
            quantity=total_quantity,
            ship_due=merge_group.earliest_due,  # 使用最早交期
            status="PENDING"
        )
        
        forming_hours, total_hours = self.time_estimator.calculate_total_time(
            merged_mo, mold_info, include_changeover=True
        )
        changeover_hours = total_hours - forming_hours
        
        # 计算节省的换模时间
        # 原本需要 N 次换模，合并后只需 1 次
        saved_changeover_hours = changeover_hours * (len(merge_group.mos) - 1)
        
        # 计算结束时间
        end_time, _, _ = self.time_estimator.calculate_end_time(
            earliest_start, merged_mo, mold_info, include_changeover=True
        )
        
        # 检查是否超过最早交期
        if end_time > merge_group.earliest_due:
            return MergeEvaluation(
                merge_group=merge_group,
                is_feasible=False,
                total_hours=total_hours,
                forming_hours=forming_hours,
                changeover_hours=changeover_hours,
                saved_changeover_hours=saved_changeover_hours,
                start_time=earliest_start,
                end_time=end_time,
                constraint_violations=["超过最早交期"]
            )
        
        # 验证约束
        validation_result = self.validator.validate_single_schedule(
            merged_mo, mold_info, merge_group.machine_id,
            earliest_start, existing_blocks
        )
        
        return MergeEvaluation(
            merge_group=merge_group,
            is_feasible=validation_result.is_valid,
            total_hours=total_hours,
            forming_hours=forming_hours,
            changeover_hours=changeover_hours,
            saved_changeover_hours=saved_changeover_hours,
            start_time=earliest_start,
            end_time=end_time,
            constraint_violations=[v.message for v in validation_result.violations]
        )
    
    def create_merged_schedule_block(
        self,
        merge_evaluation: MergeEvaluation,
        block_id: str
    ) -> Optional[ScheduleBlock]:
        """
        创建合并后的排程区块
        
        Args:
            merge_evaluation: 合并评估结果
            block_id: 区块ID
            
        Returns:
            ScheduleBlock 或 None
        """
        if not merge_evaluation.is_feasible:
            return None
        
        merge_group = merge_evaluation.merge_group
        
        return ScheduleBlock(
            block_id=block_id,
            machine_id=merge_group.machine_id,
            mold_code=merge_group.mold_code,
            start_time=merge_evaluation.start_time,
            end_time=merge_evaluation.end_time,
            mo_ids=[mo.id for mo in merge_group.mos],
            component_codes=[merge_group.component_code],
            product_display=f"{merge_group.component_code} x{len(merge_group.mos)}",
            status="SCHEDULED",
            is_merged=True
        )
    
    def optimize_merge_strategy(
        self,
        mos: List[ManufacturingOrder],
        selected_candidates: Dict[str, ScheduleCandidate],
        existing_blocks: List[ScheduleBlock]
    ) -> Tuple[List[MergeGroup], List[MergeEvaluation]]:
        """
        优化合并策略
        
        Args:
            mos: 制令列表
            selected_candidates: 已选择的候选
            existing_blocks: 现有排程区块
            
        Returns:
            (merge_groups, evaluations)
        """
        # 识别合并机会
        merge_groups = self.identify_merge_opportunities(mos, selected_candidates)
        
        # 评估每个合并组
        evaluations = []
        
        for merge_group in merge_groups:
            # 使用第一个订单的候选开始时间
            first_mo = merge_group.mos[0]
            if first_mo.id in selected_candidates:
                earliest_start = selected_candidates[first_mo.id].start_time
            else:
                earliest_start = self.config.now_datetime
            
            evaluation = self.evaluate_merge(
                merge_group, existing_blocks, earliest_start
            )
            evaluations.append(evaluation)
        
        return (merge_groups, evaluations)
    
    def generate_merge_report(
        self,
        merge_groups: List[MergeGroup],
        evaluations: List[MergeEvaluation]
    ) -> str:
        """生成合并报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("订单合并分析报告")
        lines.append("=" * 60)
        
        feasible_count = sum(1 for e in evaluations if e.is_feasible)
        total_saved_hours = sum(e.saved_changeover_hours for e in evaluations if e.is_feasible)
        
        lines.append(f"\n合并机会总数: {len(merge_groups)}")
        lines.append(f"可行合并: {feasible_count}")
        lines.append(f"总节省换模时间: {total_saved_hours:.2f}h")
        
        lines.append("\n" + "=" * 60)
        lines.append("详细分析:")
        lines.append("=" * 60)
        
        for i, (group, evaluation) in enumerate(zip(merge_groups, evaluations), 1):
            lines.append(f"\n合并组 {i}:")
            lines.append(f"  品号: {group.component_code}")
            lines.append(f"  机台: {group.machine_id}")
            lines.append(f"  订单数: {len(group.mos)}")
            lines.append(f"  总数量: {group.total_quantity}")
            lines.append(f"  交期范围: {group.earliest_due.strftime('%m/%d')} ~ {group.latest_due.strftime('%m/%d')}")
            lines.append(f"  可行性: {'是' if evaluation.is_feasible else '否'}")
            
            if evaluation.is_feasible:
                lines.append(f"  成型时间: {evaluation.forming_hours:.2f}h")
                lines.append(f"  换模时间: {evaluation.changeover_hours:.2f}h")
                lines.append(f"  节省时间: {evaluation.saved_changeover_hours:.2f}h")
                lines.append(f"  开始: {evaluation.start_time.strftime('%m/%d %H:%M')}")
                lines.append(f"  结束: {evaluation.end_time.strftime('%m/%d %H:%M')}")
            else:
                lines.append(f"  失败原因: {', '.join(evaluation.constraint_violations)}")
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)
