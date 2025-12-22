"""
候選選擇器 - Phase 3
實現交期優先 + Tie-break 規則的候選選擇邏輯
"""
from typing import List, Optional, Dict, Tuple
from datetime import datetime
from enum import Enum

from .models import ScheduleCandidate, SchedulingConfig


class TieBreakReason(str, Enum):
    """Tie-break 原因"""
    DUE_DATE = "due_date"  # 交期不同
    FORMING_TIME = "forming_time"  # 成型時間差異顯著
    YIELD_RANK = "yield_rank"  # 良率排名
    FREQUENCY = "frequency"  # 頻率（上模次數）
    FIRST_FEASIBLE = "first_feasible"  # 第一個可行候選


class CandidateScore:
    """候選評分"""
    
    def __init__(
        self,
        candidate: ScheduleCandidate,
        config: SchedulingConfig
    ):
        self.candidate = candidate
        self.config = config
        
        # 基礎分數
        self.lateness_score = self._calculate_lateness_score()
        self.forming_time_score = candidate.forming_hours
        self.yield_score = self._calculate_yield_score()
        self.frequency_score = candidate.frequency or 0
        
    def _calculate_lateness_score(self) -> float:
        """計算延遲分數（越小越好）"""
        return self.candidate.lateness_hours
    
    def _calculate_yield_score(self) -> int:
        """計算良率分數（A=1, B=2, C=3, None=999）"""
        if not self.candidate.yield_rank:
            return 999
        
        rank_map = {"A": 1, "B": 2, "C": 3}
        return rank_map.get(self.candidate.yield_rank.upper(), 999)
    
    def compare_to(
        self,
        other: 'CandidateScore'
    ) -> Tuple[int, TieBreakReason]:
        """
        與另一個候選比較
        
        Returns:
            (comparison_result, reason)
            comparison_result: -1 (self better), 0 (equal), 1 (other better)
            reason: tie-break 原因
        """
        # 1. 交期優先（延遲時間）
        if abs(self.lateness_score - other.lateness_score) > 0.01:
            if self.lateness_score < other.lateness_score:
                return (-1, TieBreakReason.DUE_DATE)
            else:
                return (1, TieBreakReason.DUE_DATE)
        
        # 2. 成型時間差異檢查（需超過門檻才比較）
        time_diff_pct = abs(self.forming_time_score - other.forming_time_score) / max(
            self.forming_time_score, other.forming_time_score, 0.01
        ) * 100
        
        if time_diff_pct >= self.config.time_threshold_pct:
            # 差異顯著，選擇成型時間較短的
            if self.forming_time_score < other.forming_time_score:
                return (-1, TieBreakReason.FORMING_TIME)
            else:
                return (1, TieBreakReason.FORMING_TIME)
        
        # 3. 良率排名（A > B > C）
        if self.yield_score != other.yield_score:
            if self.yield_score < other.yield_score:
                return (-1, TieBreakReason.YIELD_RANK)
            else:
                return (1, TieBreakReason.YIELD_RANK)
        
        # 4. 頻率（上模次數多的優先）
        if abs(self.frequency_score - other.frequency_score) > 0.01:
            if self.frequency_score > other.frequency_score:
                return (-1, TieBreakReason.FREQUENCY)
            else:
                return (1, TieBreakReason.FREQUENCY)
        
        # 完全相同
        return (0, TieBreakReason.FIRST_FEASIBLE)
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "lateness_hours": self.lateness_score,
            "forming_hours": self.forming_time_score,
            "yield_rank": self.candidate.yield_rank,
            "yield_score": self.yield_score,
            "frequency": self.frequency_score
        }


class CandidateSelector:
    """候選選擇器"""
    
    def __init__(self, config: SchedulingConfig):
        self.config = config
    
    def select_best_candidate(
        self,
        candidates: List[ScheduleCandidate]
    ) -> Optional[Tuple[ScheduleCandidate, CandidateScore, TieBreakReason]]:
        """
        從候選列表中選擇最佳候選
        
        Args:
            candidates: 候選列表
            
        Returns:
            (best_candidate, score, tie_break_reason) 或 None
        """
        if not candidates:
            return None
        
        # 只考慮可行的候選
        feasible = [c for c in candidates if c.feasible]
        
        if not feasible:
            return None
        
        # 計算所有候選的分數
        scores = [CandidateScore(c, self.config) for c in feasible]
        
        # 找出最佳候選
        best_score = scores[0]
        best_reason = TieBreakReason.FIRST_FEASIBLE
        
        for i in range(1, len(scores)):
            comparison, reason = best_score.compare_to(scores[i])
            if comparison > 0:  # current is better than best
                best_score = scores[i]
                best_reason = reason
        
        return (best_score.candidate, best_score, best_reason)
    
    def select_for_batch(
        self,
        candidates_dict: Dict[str, List[ScheduleCandidate]]
    ) -> Dict[str, Tuple[ScheduleCandidate, CandidateScore, TieBreakReason]]:
        """
        批量選擇最佳候選
        
        Args:
            candidates_dict: {mo_id: [candidates]}
            
        Returns:
            {mo_id: (best_candidate, score, reason)}
        """
        selections = {}
        
        for mo_id, candidates in candidates_dict.items():
            result = self.select_best_candidate(candidates)
            if result:
                selections[mo_id] = result
        
        return selections
    
    def rank_candidates(
        self,
        candidates: List[ScheduleCandidate]
    ) -> List[Tuple[ScheduleCandidate, CandidateScore, int]]:
        """
        對候選進行排名
        
        Args:
            candidates: 候選列表
            
        Returns:
            List[(candidate, score, rank)]，按排名順序
        """
        if not candidates:
            return []
        
        # 只考慮可行的候選
        feasible = [c for c in candidates if c.feasible]
        
        if not feasible:
            return []
        
        # 計算分數
        scored = [(c, CandidateScore(c, self.config)) for c in feasible]
        
        # 使用冒泡排序進行排名（確保 tie-break 邏輯正確）
        for i in range(len(scored)):
            for j in range(i + 1, len(scored)):
                comparison, _ = scored[i][1].compare_to(scored[j][1])
                if comparison > 0:
                    scored[i], scored[j] = scored[j], scored[i]
        
        # 添加排名
        ranked = [(c, s, i+1) for i, (c, s) in enumerate(scored)]
        
        return ranked
    
    def generate_selection_report(
        self,
        selections: Dict[str, Tuple[ScheduleCandidate, CandidateScore, TieBreakReason]]
    ) -> str:
        """生成選擇報告"""
        lines = []
        lines.append("=" * 60)
        lines.append("候選選擇報告")
        lines.append("=" * 60)
        
        lines.append(f"\n製令總數: {len(selections)}")
        
        # 統計 tie-break 原因
        reason_counts = {}
        for _, _, reason in selections.values():
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        lines.append("\nTie-break 統計:")
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {reason}: {count}")
        
        lines.append("\n" + "=" * 60)
        lines.append("詳細選擇:")
        lines.append("=" * 60)
        
        for mo_id, (candidate, score, reason) in selections.items():
            lines.append(f"\n製令: {mo_id}")
            lines.append(f"  機台: {candidate.machine_id}")
            lines.append(f"  模具: {candidate.mold_code}")
            lines.append(f"  開始: {candidate.start_time.strftime('%m/%d %H:%M')}")
            lines.append(f"  結束: {candidate.end_time.strftime('%m/%d %H:%M')}")
            lines.append(f"  延遲: {candidate.lateness_hours:.2f}h ({candidate.lateness_days:.2f}d)")
            lines.append(f"  成型時間: {candidate.forming_hours:.2f}h")
            lines.append(f"  良率: {candidate.yield_rank or 'N/A'}")
            lines.append(f"  頻率: {candidate.frequency or 0:.1f}")
            lines.append(f"  選擇原因: {reason}")
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)
    
    def generate_ranking_report(
        self,
        mo_id: str,
        ranked: List[Tuple[ScheduleCandidate, CandidateScore, int]]
    ) -> str:
        """生成排名報告"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"候選排名報告 - {mo_id}")
        lines.append("=" * 60)
        
        for candidate, score, rank in ranked[:10]:  # 只顯示前10名
            lines.append(f"\n排名 {rank}:")
            lines.append(f"  機台: {candidate.machine_id}")
            lines.append(f"  開始: {candidate.start_time.strftime('%m/%d %H:%M')}")
            lines.append(f"  延遲: {score.lateness_score:.2f}h")
            lines.append(f"  成型: {score.forming_time_score:.2f}h")
            lines.append(f"  良率: {candidate.yield_rank or 'N/A'} (分數: {score.yield_score})")
            lines.append(f"  頻率: {score.frequency_score:.1f}")
        
        if len(ranked) > 10:
            lines.append(f"\n... 還有 {len(ranked) - 10} 個候選")
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)


class CandidateComparator:
    """候選比較器 - 用於詳細比較兩個候選"""
    
    def __init__(self, config: SchedulingConfig):
        self.config = config
    
    def compare_candidates(
        self,
        candidate_a: ScheduleCandidate,
        candidate_b: ScheduleCandidate
    ) -> Tuple[str, List[str]]:
        """
        詳細比較兩個候選
        
        Returns:
            (winner, comparison_steps)
            winner: 'A', 'B', or 'EQUAL'
            comparison_steps: 比較步驟說明
        """
        steps = []
        
        score_a = CandidateScore(candidate_a, self.config)
        score_b = CandidateScore(candidate_b, self.config)
        
        # 步驟1: 可行性
        steps.append(f"步驟1 - 可行性檢查:")
        steps.append(f"  候選A: {'可行' if candidate_a.feasible else '不可行'}")
        steps.append(f"  候選B: {'可行' if candidate_b.feasible else '不可行'}")
        
        if not candidate_a.feasible and not candidate_b.feasible:
            steps.append("  結果: 都不可行")
            return ('EQUAL', steps)
        elif not candidate_a.feasible:
            steps.append("  結果: 候選B獲勝（A不可行）")
            return ('B', steps)
        elif not candidate_b.feasible:
            steps.append("  結果: 候選A獲勝（B不可行）")
            return ('A', steps)
        
        # 步驟2: 交期比較
        steps.append(f"\n步驟2 - 交期比較（延遲時間）:")
        steps.append(f"  候選A延遲: {score_a.lateness_score:.2f}h")
        steps.append(f"  候選B延遲: {score_b.lateness_score:.2f}h")
        
        if abs(score_a.lateness_score - score_b.lateness_score) > 0.01:
            if score_a.lateness_score < score_b.lateness_score:
                steps.append(f"  結果: 候選A獲勝（延遲較少）")
                return ('A', steps)
            else:
                steps.append(f"  結果: 候選B獲勝（延遲較少）")
                return ('B', steps)
        
        steps.append(f"  結果: 延遲相同，進入tie-break")
        
        # 步驟3: 成型時間比較
        time_diff_pct = abs(score_a.forming_time_score - score_b.forming_time_score) / max(
            score_a.forming_time_score, score_b.forming_time_score, 0.01
        ) * 100
        
        steps.append(f"\n步驟3 - 成型時間比較:")
        steps.append(f"  候選A成型: {score_a.forming_time_score:.2f}h")
        steps.append(f"  候選B成型: {score_b.forming_time_score:.2f}h")
        steps.append(f"  差異百分比: {time_diff_pct:.1f}%")
        steps.append(f"  門檻: {self.config.time_threshold_pct}%")
        
        if time_diff_pct >= self.config.time_threshold_pct:
            if score_a.forming_time_score < score_b.forming_time_score:
                steps.append(f"  結果: 候選A獲勝（成型時間短且差異顯著）")
                return ('A', steps)
            else:
                steps.append(f"  結果: 候選B獲勝（成型時間短且差異顯著）")
                return ('B', steps)
        
        steps.append(f"  結果: 差異不顯著，繼續tie-break")
        
        # 步驟4: 良率比較
        steps.append(f"\n步驟4 - 良率比較:")
        steps.append(f"  候選A良率: {candidate_a.yield_rank or 'N/A'} (分數: {score_a.yield_score})")
        steps.append(f"  候選B良率: {candidate_b.yield_rank or 'N/A'} (分數: {score_b.yield_score})")
        
        if score_a.yield_score != score_b.yield_score:
            if score_a.yield_score < score_b.yield_score:
                steps.append(f"  結果: 候選A獲勝（良率較高）")
                return ('A', steps)
            else:
                steps.append(f"  結果: 候選B獲勝（良率較高）")
                return ('B', steps)
        
        steps.append(f"  結果: 良率相同，繼續tie-break")
        
        # 步驟5: 頻率比較
        steps.append(f"\n步驟5 - 頻率比較（上模次數）:")
        steps.append(f"  候選A頻率: {score_a.frequency_score:.1f}")
        steps.append(f"  候選B頻率: {score_b.frequency_score:.1f}")
        
        if abs(score_a.frequency_score - score_b.frequency_score) > 0.01:
            if score_a.frequency_score > score_b.frequency_score:
                steps.append(f"  結果: 候選A獲勝（頻率較高）")
                return ('A', steps)
            else:
                steps.append(f"  結果: 候選B獲勝（頻率較高）")
                return ('B', steps)
        
        steps.append(f"  結果: 完全相同")
        
        return ('EQUAL', steps)
