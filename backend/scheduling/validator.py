"""
統一約束驗證器 - Phase 1
整合所有約束檢查，提供統一介面和違規追蹤
"""
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from enum import Enum

from .models import (
    ManufacturingOrder,
    MoldInfo,
    ScheduleBlock,
    SchedulingConfig
)
from .constraint_checker import ConstraintChecker
from .time_estimator import TimeEstimator


class ViolationType(str, Enum):
    """違規類型"""
    DOWNTIME_CONFLICT = "downtime_conflict"  # 停機衝突
    CHANGEOVER_FORBIDDEN = "changeover_forbidden"  # 換模禁區
    SHIFT_END_MISALIGN = "shift_end_misalign"  # 班次結束未對齊
    MOLD_CONCURRENCY = "mold_concurrency"  # 模具並行衝突
    MACHINE_OCCUPIED = "machine_occupied"  # 機台佔用
    WORK_CALENDAR = "work_calendar"  # 工時日曆衝突
    INSUFFICIENT_TIME = "insufficient_time"  # 時間不足


class ConstraintViolation:
    """約束違規記錄"""
    
    def __init__(
        self,
        violation_type: ViolationType,
        message: str,
        mo_id: Optional[str] = None,
        machine_id: Optional[str] = None,
        mold_code: Optional[str] = None,
        time_range: Optional[Tuple[datetime, datetime]] = None,
        severity: str = "error"
    ):
        self.violation_type = violation_type
        self.message = message
        self.mo_id = mo_id
        self.machine_id = machine_id
        self.mold_code = mold_code
        self.time_range = time_range
        self.severity = severity  # error, warning, info
        
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "type": self.violation_type,
            "message": self.message,
            "mo_id": self.mo_id,
            "machine_id": self.machine_id,
            "mold_code": self.mold_code,
            "time_range": [
                self.time_range[0].isoformat() if self.time_range else None,
                self.time_range[1].isoformat() if self.time_range else None
            ] if self.time_range else None,
            "severity": self.severity
        }


class ValidationResult:
    """驗證結果"""
    
    def __init__(self):
        self.is_valid: bool = True
        self.violations: List[ConstraintViolation] = []
        self.warnings: List[ConstraintViolation] = []
        
    def add_violation(self, violation: ConstraintViolation):
        """添加違規記錄"""
        if violation.severity == "error":
            self.is_valid = False
            self.violations.append(violation)
        elif violation.severity == "warning":
            self.warnings.append(violation)
            
    def get_summary(self) -> str:
        """獲取摘要"""
        if self.is_valid and not self.warnings:
            return "✅ 所有約束檢查通過"
        
        parts = []
        if not self.is_valid:
            parts.append(f"❌ {len(self.violations)} 個錯誤")
        if self.warnings:
            parts.append(f"⚠️ {len(self.warnings)} 個警告")
        
        return " | ".join(parts)
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "is_valid": self.is_valid,
            "summary": self.get_summary(),
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [w.to_dict() for w in self.warnings]
        }


class ScheduleValidator:
    """統一排程驗證器"""
    
    def __init__(
        self, 
        db: Session, 
        config: SchedulingConfig,
        time_estimator: TimeEstimator,
        constraint_checker: ConstraintChecker
    ):
        self.db = db
        self.config = config
        self.time_estimator = time_estimator
        self.constraint_checker = constraint_checker
        
    def validate_single_schedule(
        self,
        mo: ManufacturingOrder,
        mold_info: MoldInfo,
        machine_id: str,
        start_time: datetime,
        existing_blocks: List[ScheduleBlock]
    ) -> ValidationResult:
        """
        驗證單個排程
        
        Args:
            mo: 製令
            mold_info: 模具資訊
            machine_id: 機台ID
            start_time: 開始時間
            existing_blocks: 現有排程區塊
            
        Returns:
            ValidationResult: 驗證結果
        """
        result = ValidationResult()
        
        # 1. 計算結束時間和時間分解
        end_time, forming_hours, total_hours = self.time_estimator.calculate_end_time(
            start_time, mo, mold_info, include_changeover=True
        )
        changeover_hours = total_hours - forming_hours  # 推導換模時間
        
        # 2. 檢查停機衝突
        downtime_conflict = self.constraint_checker.check_downtime_conflict(
            machine_id, start_time, end_time
        )
        if downtime_conflict:
            result.add_violation(ConstraintViolation(
                violation_type=ViolationType.DOWNTIME_CONFLICT,
                message=f"機台 {machine_id} 在此時段有停機",
                mo_id=mo.id,
                machine_id=machine_id,
                time_range=(start_time, end_time),
                severity="error"
            ))
        
        # 3. 檢查換模禁區 (20:00-01:00)
        if changeover_hours > 0:
            forbidden_violation = self.constraint_checker.check_changeover_forbidden_zone(
                start_time, int(changeover_hours * 60)
            )
            if forbidden_violation:
                result.add_violation(ConstraintViolation(
                    violation_type=ViolationType.CHANGEOVER_FORBIDDEN,
                    message=f"換模時間 ({start_time.strftime('%H:%M')}) 落在禁區 (20:00-01:00)",
                    mo_id=mo.id,
                    machine_id=machine_id,
                    time_range=(start_time, start_time + timedelta(hours=changeover_hours)),
                    severity="error"
                ))
        
        # 4. 檢查班次結束對齊 (從 constraint_checker 讀取 shift_end_time)
        if hasattr(self.constraint_checker, 'shift_end_time'):
            if not self.constraint_checker.check_must_end_at_shift_end(end_time):
                result.add_violation(ConstraintViolation(
                    violation_type=ViolationType.SHIFT_END_MISALIGN,
                    message=f"結束時間 ({end_time.strftime('%H:%M')}) 未對齊班次結束 ({self.config.shift_end_time})",
                    mo_id=mo.id,
                    machine_id=machine_id,
                    time_range=(start_time, end_time),
                    severity="warning"
                ))
        
        # 5. 檢查模具並行衝突
        mold_conflict = self.constraint_checker.check_mold_concurrency(
            mold_info.mold_code, start_time, end_time, existing_blocks
        )
        if mold_conflict:
            result.add_violation(ConstraintViolation(
                violation_type=ViolationType.MOLD_CONCURRENCY,
                message=f"模具 {mold_info.mold_code} 在此時段已被其他機台使用",
                mo_id=mo.id,
                machine_id=machine_id,
                mold_code=mold_info.mold_code,
                time_range=(start_time, end_time),
                severity="error"
            ))
        
        # 6. 檢查機台可用性
        machine_unavailable = self.constraint_checker.check_machine_availability(
            machine_id, start_time, end_time, existing_blocks
        )
        if machine_unavailable:
            result.add_violation(ConstraintViolation(
                violation_type=ViolationType.MACHINE_OCCUPIED,
                message=f"機台 {machine_id} 在此時段已有其他排程",
                mo_id=mo.id,
                machine_id=machine_id,
                time_range=(start_time, end_time),
                severity="error"
            ))
        
        return result
    
    def validate_batch_schedules(
        self,
        schedules: List[Tuple[ManufacturingOrder, MoldInfo, str, datetime]],
        existing_blocks: List[ScheduleBlock]
    ) -> Dict[str, ValidationResult]:
        """
        批量驗證排程
        
        Args:
            schedules: [(mo, mold_info, machine_id, start_time), ...]
            existing_blocks: 現有排程區塊
            
        Returns:
            Dict[mo_id, ValidationResult]: 每個製令的驗證結果
        """
        results = {}
        
        for mo, mold_info, machine_id, start_time in schedules:
            result = self.validate_single_schedule(
                mo, mold_info, machine_id, start_time, existing_blocks
            )
            results[mo.id] = result
        
        return results
    
    def generate_violation_report(
        self,
        validation_results: Dict[str, ValidationResult]
    ) -> str:
        """
        生成違規報告
        
        Args:
            validation_results: 驗證結果字典
            
        Returns:
            str: 格式化的報告
        """
        report_lines = []
        report_lines.append("=" * 60)
        report_lines.append("📋 排程約束驗證報告")
        report_lines.append("=" * 60)
        report_lines.append("")
        
        total_schedules = len(validation_results)
        valid_count = sum(1 for r in validation_results.values() if r.is_valid)
        invalid_count = total_schedules - valid_count
        
        report_lines.append(f"📊 統計:")
        report_lines.append(f"   總排程數: {total_schedules}")
        report_lines.append(f"   ✅ 通過: {valid_count}")
        report_lines.append(f"   ❌ 失敗: {invalid_count}")
        report_lines.append("")
        
        if invalid_count > 0:
            report_lines.append("=" * 60)
            report_lines.append("❌ 違規詳情:")
            report_lines.append("=" * 60)
            
            for mo_id, result in validation_results.items():
                if not result.is_valid:
                    report_lines.append(f"\n📋 製令: {mo_id}")
                    for violation in result.violations:
                        report_lines.append(f"   ❌ [{violation.violation_type}] {violation.message}")
                        if violation.time_range:
                            start, end = violation.time_range
                            report_lines.append(f"      時間: {start.strftime('%m/%d %H:%M')} ~ {end.strftime('%m/%d %H:%M')}")
        
        # 警告摘要
        warning_count = sum(len(r.warnings) for r in validation_results.values())
        if warning_count > 0:
            report_lines.append("")
            report_lines.append("=" * 60)
            report_lines.append(f"⚠️ 警告摘要: {warning_count} 個")
            report_lines.append("=" * 60)
            
            for mo_id, result in validation_results.items():
                if result.warnings:
                    report_lines.append(f"\n📋 製令: {mo_id}")
                    for warning in result.warnings:
                        report_lines.append(f"   ⚠️ [{warning.violation_type}] {warning.message}")
        
        report_lines.append("")
        report_lines.append("=" * 60)
        
        return "\n".join(report_lines)
