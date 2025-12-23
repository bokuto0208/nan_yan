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
                # 如果component_code包含多個子件（逗號分隔），則用 / 分隔顯示
                component_list = mo.component_code.split(',') if ',' in mo.component_code else [mo.component_code]
                display_text = ','.join(component_list) if len(component_list) > 1 else mo.component_code
                
                block = ScheduleBlock(
                    block_id=f"BLOCK-{block_counter:03d}",
                    machine_id=best_candidate.machine_id,
                    mold_code=best_candidate.mold_code,
                    start_time=best_candidate.start_time,
                    end_time=best_candidate.end_time,
                    mo_ids=[mo.id],
                    component_codes=component_list,
                    product_display=display_text,
                    status="SCHEDULED",
                    is_merged=True if len(component_list) > 1 else False
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
    
    def schedule_fill_all_machines(
        self,
        mos: List[ManufacturingOrder],
        existing_blocks: Optional[List[ScheduleBlock]] = None
    ) -> ScheduleResult:
        """
        執行填滿所有機台的排程模式
        
        策略：
        1. 對每個製令，尋找所有適配的機台
        2. 在每台機台上找第一個可用空檔
        3. 選擇最早有空檔的機台（不追求最優，只求填滿）
        4. 確保製令之間絕對不重疊
        
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
            message="填滿機台模式排程開始"
        )
        
        try:
            # 步驟1: 按交期排序
            sorted_mos = sorted(mos, key=lambda mo: (mo.ship_due, mo.priority))
            
            # 步驟2: 獲取所有可用機台
            from database import Machine
            all_machines = self.db.query(Machine).all()
            machine_ids = [m.machine_id for m in all_machines]
            
            print(f"🎯 填滿機台模式：找到 {len(machine_ids)} 台機台，待排 {len(sorted_mos)} 個製令")
            
            # 步驟3: 維護全局的排程區塊列表（用於檢測衝突）
            all_scheduled_blocks = list(existing_blocks)
            
            # 步驟4: 逐個製令尋找可用機台空檔
            block_counter = 1
            
            for idx, mo in enumerate(sorted_mos, 1):
                print(f"\n🔍 [{idx}/{len(sorted_mos)}] 處理製令 {mo.id} (交期: {mo.ship_due.strftime('%Y-%m-%d')})")
                
                best_machine = None
                best_candidate = None
                earliest_available_time = None
                
                # 為所有機台生成候選（讓候選生成器內部處理適配性）
                # 傳入全局區塊列表，讓候選生成器為每台適配機台找空檔
                all_candidates = self.candidate_generator.generate_candidates_for_mo(mo, all_scheduled_blocks)
                
                print(f"  📋 總共生成 {len(all_candidates)} 個候選")
                
                if not all_candidates:
                    result.failed_mos.append(mo.id)
                    print(f"  ❌ 無可用候選時段")
                    continue
                
                # 選擇最早的候選
                best_candidate = min(all_candidates, key=lambda c: c.start_time)
                best_machine = best_candidate.machine_id
                
                print(f"  🎯 選擇機台 {best_machine}")
                print(f"     時段: {best_candidate.start_time.strftime('%m/%d %H:%M')} - {best_candidate.end_time.strftime('%m/%d %H:%M')}")
                
                # 如果找到可用空檔
                if best_machine and best_candidate:
                    # 雙重驗證：檢查該時段是否真的沒有衝突
                    machine_blocks = [b for b in all_scheduled_blocks if b.machine_id == best_machine]
                    has_conflict = False
                    
                    for existing_block in machine_blocks:
                        # 檢查時間重疊
                        if (best_candidate.start_time < existing_block.end_time and 
                            best_candidate.end_time > existing_block.start_time):
                            print(f"  ⚠️ 衝突檢測: 與區塊 {existing_block.block_id} 重疊")
                            print(f"     新區塊: {best_candidate.start_time.strftime('%m/%d %H:%M')} - {best_candidate.end_time.strftime('%m/%d %H:%M')}")
                            print(f"     現有: {existing_block.start_time.strftime('%m/%d %H:%M')} - {existing_block.end_time.strftime('%m/%d %H:%M')}")
                            has_conflict = True
                            break
                    
                    if has_conflict:
                        result.failed_mos.append(mo.id)
                        print(f"  ❌ 候選時段驗證失敗：存在時間衝突")
                        continue
                    
                    # 創建排程區塊
                    component_list = mo.component_code.split(',') if ',' in mo.component_code else [mo.component_code]
                    display_text = '/'.join(component_list) if len(component_list) > 1 else mo.component_code
                    
                    block = ScheduleBlock(
                        block_id=f"FILL-{block_counter:03d}",
                        machine_id=best_machine,
                        mold_code=self._get_mold_code_for_mo(mo),
                        start_time=best_candidate.start_time,
                        end_time=best_candidate.end_time,
                        mo_ids=[mo.id],
                        component_codes=component_list,
                        product_display=display_text,
                        status="SCHEDULED",
                        is_merged=len(component_list) > 1
                    )
                    
                    # 立即添加到全局區塊列表（防止下次排程時重疊）
                    all_scheduled_blocks.append(block)
                    result.scheduled_mos.append(mo.id)
                    result.blocks.append(block)
                    
                    print(f"  ✅ 排入機台 {best_machine}")
                    print(f"     時段: {best_candidate.start_time.strftime('%m/%d %H:%M')} - {best_candidate.end_time.strftime('%m/%d %H:%M')}")
                    print(f"     該機台現有區塊數: {len([b for b in all_scheduled_blocks if b.machine_id == best_machine])}")
                    
                    block_counter += 1
                else:
                    result.failed_mos.append(mo.id)
                    print(f"  ❌ 所有適配機台都無可用空檔")
            
            # 分割跨日區塊
            result.blocks = self.block_splitter.split_blocks_by_workday(result.blocks)
            
            # 計算KPI
            kpi_data = self._calculate_kpi(result.blocks, sorted_mos)
            result.total_mos = kpi_data["total_orders"]
            result.on_time_count = kpi_data["on_time_orders"] 
            result.late_count = kpi_data["delayed_orders"]
            result.total_lateness_days = kpi_data["avg_lateness_hours"] / 24 if kpi_data["avg_lateness_hours"] > 0 else 0
            result.changeover_count = len(result.blocks)
            
            # 生成延迟報告
            result.delay_reports = self._generate_delay_reports(result.blocks, sorted_mos)
            
            if result.failed_mos:
                result.success = False
                result.message = f"填滿機台排程部分完成: {len(result.scheduled_mos)}/{len(sorted_mos)} 成功"
            else:
                result.message = f"填滿機台排程完成: {len(result.scheduled_mos)}/{len(sorted_mos)} 全部成功"
            
            print(f"\n🎯 填滿機台排程完成:")
            print(f"   ✅ 成功: {len(result.scheduled_mos)}")
            print(f"   ❌ 失敗: {len(result.failed_mos)}")
            print(f"   📊 總區塊數: {len(result.blocks)}")
            
        except Exception as e:
            import traceback
            result.success = False
            result.message = f"填滿機台排程失败: {str(e)}"
            print(f"❌ 填滿機台排程錯誤: {e}")
            traceback.print_exc()
        
        return result
    
    def _is_machine_compatible(self, mo: ManufacturingOrder, machine_id: str) -> bool:
        """檢查製令是否與機台適配"""
        # 獲取模具編號
        mold_code = self._get_mold_code_for_mo(mo)
        if not mold_code:
            return False
        
        # 檢查MoldData表中是否有該模具+機台的記錄
        from database import MoldData
        compatible = self.db.query(MoldData).filter(
            MoldData.mold_code == mold_code,
            MoldData.machine_id == machine_id
        ).first()
        
        return compatible is not None
    
    def _get_mold_code_for_mo(self, mo: ManufacturingOrder) -> Optional[str]:
        """從製令獲取模具編號
        
        注意：多子件製令一定共用同個模具，因此從第一個子件查找即可
        """
        # 取第一個子件查找模具編號（多子件共用同模具）
        first_component = mo.component_code.split(',')[0] if ',' in mo.component_code else mo.component_code
        
        from database import MoldData
        mold_data = self.db.query(MoldData).filter(
            MoldData.component_code == first_component
        ).first()
        
        return mold_data.mold_code if mold_data else None
