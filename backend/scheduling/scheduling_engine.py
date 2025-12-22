"""
EPS 生产排程引擎 - Phase 5
整合所有模块，提供完整的排程功能
"""
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from .models import (
    ManufacturingOrder,
    ScheduleBlock,
    SchedulingConfig,
    ScheduleResult,
    ScheduleCandidate,
    MOStatus
)
from .time_estimator import TimeEstimator
from .constraint_checker import ConstraintChecker
from .validator import ScheduleValidator
from .gap_calculator import GapCalculator
from .candidate_generator import CandidateGenerator
from .candidate_selector import CandidateSelector
from .order_merger import OrderMerger
from .block_splitter import BlockSplitter


class SchedulingEngine:
    """EPS 排程引擎"""
    
    def __init__(self, db: Session, config: Optional[SchedulingConfig] = None):
        self.db = db
        self.config = config or SchedulingConfig()
        
        # 先初始化 ConstraintChecker
        self.constraint_checker = ConstraintChecker(db, self.config)
        
        # 初始化 TimeEstimator 時傳入 ConstraintChecker
        self.time_estimator = TimeEstimator(db, self.config, self.constraint_checker)
        
        # 初始化其他組件
        self.validator = ScheduleValidator(
            db, self.config, self.time_estimator, self.constraint_checker
        )
        self.gap_calculator = GapCalculator(
            db, self.config, self.constraint_checker
        )
        self.candidate_generator = CandidateGenerator(
            db, self.config, self.time_estimator, self.constraint_checker,
            self.validator, self.gap_calculator
        )
        self.candidate_selector = CandidateSelector(self.config)
        self.order_merger = OrderMerger(
            db, self.config, self.time_estimator, 
            self.constraint_checker, self.validator
        )
        self.block_splitter = BlockSplitter(db, self.config, self.constraint_checker)
        
    def schedule(
        self,
        mos: List[ManufacturingOrder],
        existing_blocks: Optional[List[ScheduleBlock]] = None
    ) -> ScheduleResult:
        """
        执行完整排程
        
        Args:
            mos: 待排程的制令列表
            existing_blocks: 现有排程区块
            
        Returns:
            ScheduleResult: 排程结果
        """
        if existing_blocks is None:
            existing_blocks = []
        
        result = ScheduleResult(
            success=True,
            message="排程开始"
        )
        
        try:
            # 步骤1: 按交期排序
            sorted_mos = sorted(mos, key=lambda mo: (mo.ship_due, mo.priority))
            
            # 步骤2-5: 逐个排程（保证顺序性）
            merged_blocks = []
            independent_blocks = []
            merged_mo_ids = set()
            block_counter = 1
            current_blocks = existing_blocks.copy()
            
            # 如果启用合并，先识别合并机会
            if self.config.merge_enabled:
                # 先为所有订单生成候选
                all_candidates = self.candidate_generator.generate_batch_candidates(
                    sorted_mos, current_blocks
                )
                selections = self.candidate_selector.select_for_batch(all_candidates)
                selected_candidates = {mo_id: cand for mo_id, (cand, _, _) in selections.items()}
                
                # 识别合并组
                merge_groups, evaluations = self.order_merger.optimize_merge_strategy(
                    sorted_mos, selected_candidates, current_blocks
                )
                
                # 处理合并区块
                for i, evaluation in enumerate(evaluations):
                    if evaluation.is_feasible:
                        block_id = f"MERGED-{block_counter:03d}"
                        merged_block = self.order_merger.create_merged_schedule_block(
                            evaluation, block_id
                        )
                        
                        if merged_block:
                            merged_blocks.append(merged_block)
                            merged_mo_ids.update(mo.id for mo in evaluation.merge_group.mos)
                            current_blocks.append(merged_block)
                            
                            # 记录合并信息
                            for mo in evaluation.merge_group.mos:
                                result.scheduled_mos.append(mo.id)
                                result.change_log.append(
                                    f"制令 {mo.id} 已合并到区块 {block_id}"
                                )
                            
                            block_counter += 1
            
            # 为未合并的订单逐个排程
            for mo in sorted_mos:
                if mo.id in merged_mo_ids:
                    continue
                
                # 为单个订单生成候选（基于当前已有区块）
                candidates = self.candidate_generator.generate_candidates_for_mo(
                    mo, current_blocks
                )
                
                if not candidates:
                    result.failed_mos.append(mo.id)
                    result.change_log.append(f"制令 {mo.id} 排程失败: 无可行候选")
                    continue
                
                # 选择最佳候选
                selection_result = self.candidate_selector.select_best_candidate(candidates)
                
                if not selection_result:
                    result.failed_mos.append(mo.id)
                    result.change_log.append(f"制令 {mo.id} 排程失败: 无可行候选（所有候選都不可行）")
                    continue
                
                best_candidate, score, reason = selection_result
                
                # 创建排程区块
                block = ScheduleBlock(
                    block_id=f"BLOCK-{block_counter:03d}",
                    machine_id=best_candidate.machine_id,
                    mold_code=best_candidate.mold_code,
                    start_time=best_candidate.start_time,
                    end_time=best_candidate.end_time,
                    mo_ids=[mo.id],
                    component_codes=[mo.component_code],
                    product_display=mo.component_code,
                    status="SCHEDULED",
                    is_merged=False
                )
                
                independent_blocks.append(block)
                result.scheduled_mos.append(mo.id)
                
                # 将新区块添加到当前区块列表，以便下一个订单基于此排程
                current_blocks.append(block)
                
                block_counter += 1
            
            # 步骤6: 合并所有区块
            result.blocks = merged_blocks + independent_blocks
            
            # 步骤6.5: 分割跨日區塊
            result.blocks = self.block_splitter.split_blocks_by_workday(result.blocks)
            
            # 步骤7: 计算KPI
            kpi_data = self._calculate_kpi(result.blocks, sorted_mos)
            result.total_mos = kpi_data["total_orders"]
            result.on_time_count = kpi_data["on_time_orders"]
            result.late_count = kpi_data["delayed_orders"]
            result.total_lateness_days = kpi_data["avg_lateness_hours"] / 24 if kpi_data["avg_lateness_hours"] > 0 else 0
            result.changeover_count = len(result.blocks)  # 简化：每个区块至少一次换模
            
            # 步骤8: 生成延迟报告
            result.delay_reports = self._generate_delay_reports(result.blocks, sorted_mos)
            
            # 更新消息
            if result.failed_mos:
                result.success = False
                result.message = f"排程部分完成: {len(result.scheduled_mos)}/{len(sorted_mos)} 成功"
            else:
                result.message = f"排程成功: {len(result.scheduled_mos)} 个制令已排程"
            
        except Exception as e:
            import traceback
            result.success = False
            result.message = f"排程失败: {str(e)}"
            result.change_log.append(f"错误: {str(e)}")
            # 打印完整錯誤追蹤
            print("=" * 80)
            print("排程引擎錯誤追蹤:")
            print("=" * 80)
            traceback.print_exc()
            print("=" * 80)
        
        return result
    
    def incremental_schedule(
        self,
        new_mos: List[ManufacturingOrder],
        existing_result: ScheduleResult
    ) -> ScheduleResult:
        """
        增量排程（添加新订单到现有排程）
        
        Args:
            new_mos: 新的制令列表
            existing_result: 现有排程结果
            
        Returns:
            ScheduleResult: 更新后的排程结果
        """
        # 将现有区块作为约束
        return self.schedule(new_mos, existing_result.blocks)
    
    def reschedule(
        self,
        mo_ids: List[str],
        all_mos: List[ManufacturingOrder],
        existing_blocks: List[ScheduleBlock]
    ) -> ScheduleResult:
        """
        重新排程指定的制令
        
        Args:
            mo_ids: 需要重排的制令ID列表
            all_mos: 所有制令
            existing_blocks: 现有排程区块
            
        Returns:
            ScheduleResult: 排程结果
        """
        # 过滤出需要重排的制令
        mos_to_reschedule = [mo for mo in all_mos if mo.id in mo_ids]
        
        # 移除相关的现有区块
        filtered_blocks = [
            block for block in existing_blocks
            if not any(mo_id in block.mo_ids for mo_id in mo_ids)
        ]
        
        return self.schedule(mos_to_reschedule, filtered_blocks)
    
    def validate_schedule(
        self,
        blocks: List[ScheduleBlock]
    ) -> Dict[str, any]:
        """
        验证排程结果
        
        Args:
            blocks: 排程区块列表
            
        Returns:
            验证报告
        """
        report = {
            "is_valid": True,
            "total_blocks": len(blocks),
            "violations": [],
            "warnings": []
        }
        
        # 检查时间重叠
        for i, block1 in enumerate(blocks):
            for block2 in blocks[i+1:]:
                if block1.machine_id == block2.machine_id:
                    if self._check_overlap(
                        block1.start_time, block1.end_time,
                        block2.start_time, block2.end_time
                    ):
                        report["is_valid"] = False
                        report["violations"].append(
                            f"机台 {block1.machine_id} 时间冲突: "
                            f"{block1.block_id} vs {block2.block_id}"
                        )
                
                # 检查模具冲突
                if block1.mold_code == block2.mold_code:
                    if self._check_overlap(
                        block1.start_time, block1.end_time,
                        block2.start_time, block2.end_time
                    ):
                        report["is_valid"] = False
                        report["violations"].append(
                            f"模具 {block1.mold_code} 并行冲突: "
                            f"{block1.block_id} vs {block2.block_id}"
                        )
        
        return report
    
    def _calculate_kpi(
        self,
        blocks: List[ScheduleBlock],
        mos: List[ManufacturingOrder]
    ) -> Dict[str, any]:
        """计算KPI指标"""
        kpi = {
            "total_orders": len(mos),
            "scheduled_orders": 0,
            "merged_orders": 0,
            "total_blocks": len(blocks),
            "merged_blocks": 0,
            "on_time_orders": 0,
            "delayed_orders": 0,
            "avg_lateness_hours": 0.0,
            "max_lateness_hours": 0.0,
            "total_forming_hours": 0.0,
            "total_changeover_hours": 0.0,
            "utilization_rate": 0.0
        }
        
        # 创建订单到区块的映射
        mo_to_block = {}
        for block in blocks:
            for mo_id in block.mo_ids:
                mo_to_block[mo_id] = block
        
        lateness_list = []
        
        for mo in mos:
            if mo.id in mo_to_block:
                kpi["scheduled_orders"] += 1
                block = mo_to_block[mo.id]
                
                if block.is_merged:
                    kpi["merged_orders"] += 1
                
                # 计算延迟
                if block.end_time > mo.ship_due:
                    kpi["delayed_orders"] += 1
                    lateness_hours = (block.end_time - mo.ship_due).total_seconds() / 3600
                    lateness_list.append(lateness_hours)
                else:
                    kpi["on_time_orders"] += 1
        
        # 统计区块
        for block in blocks:
            if block.is_merged:
                kpi["merged_blocks"] += 1
            
            # 计算时间（需要从候选信息获取，这里简化处理）
            duration_hours = (block.end_time - block.start_time).total_seconds() / 3600
            kpi["total_forming_hours"] += duration_hours
        
        # 计算平均和最大延迟
        if lateness_list:
            kpi["avg_lateness_hours"] = sum(lateness_list) / len(lateness_list)
            kpi["max_lateness_hours"] = max(lateness_list)
        
        return kpi
    
    def _generate_delay_reports(
        self,
        blocks: List[ScheduleBlock],
        mos: List[ManufacturingOrder]
    ) -> List[Dict[str, any]]:
        """生成延迟报告"""
        reports = []
        
        # 创建订单到区块的映射
        mo_to_block = {}
        for block in blocks:
            for mo_id in block.mo_ids:
                mo_to_block[mo_id] = block
        
        for mo in mos:
            if mo.id in mo_to_block:
                block = mo_to_block[mo.id]
                
                if block.end_time > mo.ship_due:
                    lateness_hours = (block.end_time - mo.ship_due).total_seconds() / 3600
                    lateness_days = lateness_hours / 24
                    
                    reports.append({
                        "mo_id": mo.id,
                        "ship_due": mo.ship_due.isoformat(),
                        "actual_end": block.end_time.isoformat(),
                        "lateness_hours": round(lateness_hours, 2),
                        "lateness_days": round(lateness_days, 2),
                        "machine_id": block.machine_id
                    })
        
        return reports
    
    def _check_overlap(
        self,
        start1: datetime,
        end1: datetime,
        start2: datetime,
        end2: datetime
    ) -> bool:
        """检查两个时间段是否重叠"""
        return start1 < end2 and start2 < end1
    
    def generate_schedule_report(
        self,
        result: ScheduleResult
    ) -> str:
        """生成排程报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("EPS 生产排程报告")
        lines.append("=" * 70)
        
        lines.append(f"\n状态: {'成功' if result.success else '失败'}")
        lines.append(f"消息: {result.message}")
        
        # KPI统计
        lines.append("\n" + "=" * 70)
        lines.append("KPI 统计")
        lines.append("=" * 70)
        
        lines.append(f"总订单数: {result.total_mos}")
        lines.append(f"已排程: {len(result.scheduled_mos)}")
        lines.append(f"失败: {len(result.failed_mos)}")
        
        # 计算合并订单数
        merged_mo_count = sum(len(b.mo_ids) for b in result.blocks if b.is_merged)
        merged_block_count = sum(1 for b in result.blocks if b.is_merged)
        
        lines.append(f"合并订单: {merged_mo_count}")
        lines.append(f"总区块数: {len(result.blocks)}")
        lines.append(f"合并区块: {merged_block_count}")
        lines.append(f"准时完成: {result.on_time_count}")
        lines.append(f"延迟订单: {result.late_count}")
        
        if result.late_count > 0:
            lines.append(f"平均延迟: {result.total_lateness_days:.2f}d")
            # 最大延迟需要从delay_reports计算
            if result.delay_reports:
                max_lateness = max(r['lateness_days'] for r in result.delay_reports)
                lines.append(f"最大延迟: {max_lateness:.2f}d")
        
        # 排程区块
        lines.append("\n" + "=" * 70)
        lines.append(f"排程区块 (共 {len(result.blocks)} 个)")
        lines.append("=" * 70)
        
        for block in sorted(result.blocks, key=lambda b: (b.machine_id, b.start_time)):
            lines.append(f"\n{block.block_id}:")
            lines.append(f"  机台: {block.machine_id}")
            lines.append(f"  模具: {block.mold_code}")
            lines.append(f"  订单: {', '.join(block.mo_ids)}")
            lines.append(f"  品号: {block.product_display}")
            lines.append(f"  时间: {block.start_time.strftime('%m/%d %H:%M')} ~ {block.end_time.strftime('%m/%d %H:%M')}")
            lines.append(f"  状态: {block.status}")
            if block.is_merged:
                lines.append(f"  **已合并** ({len(block.mo_ids)} 个订单)")
        
        # 延迟报告
        if result.delay_reports:
            lines.append("\n" + "=" * 70)
            lines.append(f"延迟报告 (共 {len(result.delay_reports)} 个)")
            lines.append("=" * 70)
            
            for report in result.delay_reports:
                lines.append(f"\n订单: {report['mo_id']}")
                lines.append(f"  交期: {datetime.fromisoformat(report['ship_due']).strftime('%m/%d %H:%M')}")
                lines.append(f"  完成: {datetime.fromisoformat(report['actual_end']).strftime('%m/%d %H:%M')}")
                lines.append(f"  延迟: {report['lateness_hours']}h ({report['lateness_days']}d)")
                lines.append(f"  机台: {report['machine_id']}")
        
        # 失败订单
        if result.failed_mos:
            lines.append("\n" + "=" * 70)
            lines.append(f"失败订单 (共 {len(result.failed_mos)} 个)")
            lines.append("=" * 70)
            
            for mo_id in result.failed_mos:
                lines.append(f"  {mo_id}")
        
        lines.append("\n" + "=" * 70)
        
        return "\n".join(lines)
