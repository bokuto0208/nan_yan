"""
時間估算器 - 計算半成品的成型時間和換模時間
"""
from typing import Optional, Dict, Tuple, List, TYPE_CHECKING
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import MoldCalculation
from .models import ManufacturingOrder, MoldInfo, SchedulingConfig

if TYPE_CHECKING:
    from .constraint_checker import ConstraintChecker


class TimeEstimator:
    """時間估算器 - 針對半成品"""
    
    def __init__(self, db: Session, config: SchedulingConfig, constraint_checker: Optional['ConstraintChecker'] = None):
        self.db = db
        self.config = config
        self.constraint_checker = constraint_checker
        self._mold_cache: Dict[str, MoldInfo] = {}
        self._changeover_cache: Dict[str, int] = {}
    
    def get_mold_info(self, component_code: str, machine_id: str) -> Optional[MoldInfo]:
        """
        查詢半成品在特定機台的模具資訊
        
        Args:
            component_code: 半成品品號(1開頭)
            machine_id: 機台編號
            
        Returns:
            模具資訊,若無則返回 None
        """
        cache_key = f"{component_code}_{machine_id}"
        
        if cache_key in self._mold_cache:
            return self._mold_cache[cache_key]
        
        # 從 mold_calculations 查詢資料庫
        mold = self.db.query(MoldCalculation).filter(
            MoldCalculation.component_code == component_code,
            MoldCalculation.machine_id == machine_id,
            MoldCalculation.cavity_count.isnot(None),
            MoldCalculation.cavity_count > 0,
            MoldCalculation.avg_molding_time_sec.isnot(None),
            MoldCalculation.avg_molding_time_sec > 0
        ).first()
        
        if not mold:
            return None
        
        # 從 MoldData 補充 frequency 和 yield_rank
        from database import MoldData
        mold_data = self.db.query(MoldData).filter(
            MoldData.component_code == component_code,
            MoldData.machine_id == machine_id
        ).first()
        
        mold_info = MoldInfo(
            mold_code=mold.mold_code,
            component_code=mold.component_code,
            machine_id=mold.machine_id,
            cavity_count=mold.cavity_count,
            avg_molding_time=mold.avg_molding_time_sec,
            frequency=mold_data.frequency if mold_data else None,
            yield_rank=mold_data.yield_rank if mold_data else None
        )
        
        self._mold_cache[cache_key] = mold_info
        return mold_info
    
    def get_changeover_time(self, component_code: str, machine_id: str = None) -> int:
        """
        查詢半成品的換模時間（從 mold_calculations）
        
        Args:
            component_code: 半成品品號(1開頭)
            machine_id: 機台編號（可選，更精確）
            
        Returns:
            換模時間(分鐘),若無資料則返回預設值
        """
        cache_key = f"{component_code}_{machine_id}" if machine_id else component_code
        
        if cache_key in self._changeover_cache:
            return self._changeover_cache[cache_key]
        
        # 從 mold_calculations 查詢換模時間
        query = self.db.query(MoldCalculation).filter(
            MoldCalculation.component_code == component_code,
            MoldCalculation.mold_change_time_min.isnot(None)
        )
        
        if machine_id:
            query = query.filter(MoldCalculation.machine_id == machine_id)
        
        mold = query.first()
        
        changeover_time = self.config.default_changeover_minutes
        if mold and mold.mold_change_time_min:
            changeover_time = int(mold.mold_change_time_min)
        
        self._changeover_cache[cache_key] = changeover_time
        return changeover_time
    
    def calculate_forming_time(
        self, 
        mo: ManufacturingOrder, 
        mold_info: MoldInfo
    ) -> float:
        """
        計算成型時間（直接從 mold_calculations 讀取，按比例調整）
        
        Args:
            mo: 製令
            mold_info: 模具資訊
            
        Returns:
            成型時間(小時)
        """
        # 從 mold_calculations 查詢預計算的時間
        mold_calc = self.db.query(MoldCalculation).filter(
            MoldCalculation.component_code == mo.component_code,
            MoldCalculation.machine_id == mold_info.machine_id
        ).first()
        
        if not mold_calc:
            # 備用計算：直接用模具資訊計算
            shot_count = mo.quantity / mold_info.cavity_count
            total_seconds = shot_count * mold_info.avg_molding_time
            return total_seconds / 3600
        
        # 如果 needed_quantity = 0，使用直接計算
        if not mold_calc.needed_quantity or mold_calc.needed_quantity == 0:
            shot_count = mo.quantity / mold_info.cavity_count
            total_seconds = shot_count * mold_info.avg_molding_time
            return total_seconds / 3600
        
        # 從含換模的總時間中扣除換模時間，得到純成型時間
        changeover_min = mold_calc.mold_change_time_min or 0
        forming_min = (mold_calc.total_time_with_change_min or 0) - changeover_min
        
        # 按比例調整時間：(實際數量 / mold_calc 計算的數量) * 成型時間
        forming_hours = (mo.quantity / mold_calc.needed_quantity) * (forming_min / 60)
        
        return forming_hours
    
    def calculate_total_time(
        self,
        mo: ManufacturingOrder,
        mold_info: MoldInfo,
        include_changeover: bool = True
    ) -> Tuple[float, float]:
        """
        計算總時間（直接從 mold_calculations 讀取 total_time_with_change_min，按比例調整）
        
        Args:
            mo: 製令
            mold_info: 模具資訊
            include_changeover: 是否包含換模時間
            
        Returns:
            (成型時間(小時), 總時間(小時))
        """
        # 計算成型時間
        forming_hours = self.calculate_forming_time(mo, mold_info)
        
        # 獲取換模時間（固定值，不按比例調整）
        changeover_hours = 0
        if include_changeover:
            changeover_minutes = self.get_changeover_time(mo.component_code, mold_info.machine_id)
            changeover_hours = changeover_minutes / 60
        
        total_hours = forming_hours + changeover_hours
        
        return forming_hours, total_hours
    
    def calculate_end_time(
        self,
        start_time: datetime,
        mo: ManufacturingOrder,
        mold_info: MoldInfo,
        include_changeover: bool = True
    ) -> Tuple[datetime, float, float]:
        """
        計算完成時間（考慮工作日曆）
        
        Args:
            start_time: 開始時間
            mo: 製令
            mold_info: 模具資訊
            include_changeover: 是否包含換模時間
            
        Returns:
            (完成時間, 成型時間(小時), 總時間(小時))
        """
        forming_hours, total_hours = self.calculate_total_time(
            mo, mold_info, include_changeover
        )
        
        # 如果沒有 ConstraintChecker，直接加總時數
        if not self.constraint_checker:
            end_time = start_time + timedelta(hours=total_hours)
            return end_time, forming_hours, total_hours
        
        # 使用 ConstraintChecker 獲取工作時間區間
        # 搜尋範圍：從開始時間到30天後（足夠長）
        search_end = start_time + timedelta(days=30)
        work_intervals = self.constraint_checker.get_work_intervals(start_time, search_end)
        
        if not work_intervals:
            # 如果沒有工作日曆，直接加總時數
            end_time = start_time + timedelta(hours=total_hours)
            return end_time, forming_hours, total_hours
        
        # 從 start_time 開始累積工作時間
        remaining_hours = total_hours
        current_time = start_time
        
        # 如果開始時間不在任何工作區間內，調整到下一個工作區間開始
        in_work_interval = False
        for interval in work_intervals:
            if interval.start_time <= current_time < interval.end_time:
                in_work_interval = True
                break
        
        if not in_work_interval:
            # 找到第一個在 start_time 之後的工作區間
            for interval in work_intervals:
                if interval.start_time > current_time:
                    current_time = interval.start_time
                    break
        
        for interval in work_intervals:
            # 如果當前時間在此區間之前，跳到區間開始
            if current_time < interval.start_time:
                current_time = interval.start_time
            
            # 如果當前時間在此區間之後，繼續下一個區間
            if current_time >= interval.end_time:
                continue
            
            # 計算此區間的可用時間
            available_hours = (interval.end_time - current_time).total_seconds() / 3600
            
            if available_hours >= remaining_hours:
                # 此區間足夠完成剩餘工作
                end_time = current_time + timedelta(hours=remaining_hours)
                return end_time, forming_hours, total_hours
            else:
                # 用完此區間，繼續下一個區間
                remaining_hours -= available_hours
                current_time = interval.end_time
        
        # 如果所有區間都用完還沒完成，在最後時間點繼續（異常情況）
        end_time = current_time + timedelta(hours=remaining_hours)
        return end_time, forming_hours, total_hours
    
    def calculate_lateness(
        self,
        end_time: datetime,
        ship_due: datetime
    ) -> Tuple[float, float, bool]:
        """
        計算延遲
        
        Args:
            end_time: 完成時間
            ship_due: 交期
            
        Returns:
            (延遲小時數, 延遲天數, 是否準時)
        """
        delta = end_time - ship_due
        
        if delta.total_seconds() <= 0:
            return 0, 0, True
        
        lateness_hours = delta.total_seconds() / 3600
        lateness_days = lateness_hours / 24
        
        return lateness_hours, lateness_days, False
    
    def get_available_machines(self, component_code: str) -> List[str]:
        """
        獲取半成品可用的機台列表(相容性)
        
        Args:
            component_code: 半成品品號(1開頭)
            
        Returns:
            機台ID列表
        """
        machines = self.db.query(MoldCalculation.machine_id).filter(
            MoldCalculation.component_code == component_code,
            MoldCalculation.machine_id.isnot(None),
            MoldCalculation.cavity_count.isnot(None),
            MoldCalculation.cavity_count > 0,
            MoldCalculation.avg_molding_time_sec.isnot(None),
            MoldCalculation.avg_molding_time_sec > 0
        ).distinct().all()
        
        return [m[0] for m in machines]
