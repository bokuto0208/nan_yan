import React, { useState, useRef, useEffect, useMemo } from 'react'
import { useTimeline } from '../hooks/useTimeline'
import { api } from '../api/api'
import { Order } from '../types'
import styles from './Scheduling.module.css'

type WorkOrder = {
  id: string
  orderId: string
  productId: string
  machineId: string
  startHour: number
  endHour: number
  scheduledDate?: string  // 排程日期 (YYYY-MM-DD)，來自後端區塊分割
  status: 'running' | 'idle'
  aiLocked: boolean
  linkedOrderId?: string  // ID of the linked split order part (連結的分割訂單ID)
  isSplit?: boolean       // Whether this order is part of a split (是否為分割訂單)
  splitPart?: number      // Which part of the split (1, 2, 3...) (分割部分編號)
  totalSplits?: number    // Total number of splits (總共分割成幾段)
  originalId?: string     // The original ID from database before modification/split (修改/分割前的原始資料庫ID)
  isModified?: boolean    // Whether this order has been modified (是否已修改)
}

/**
 * 後端回傳的 isSplit / splitPart / totalSplits 可能因「部分更新」或 total_sequences 設定而不一致。
 * 前端以 (orderId, productId) 重新分組後計算分段資訊，確保：
 * - 同一製令 + 子件的多段卡片一定能同步拖動
 * - 分段標籤顯示穩定
 * 
 * 注意：當查詢特定日期時，可能只看到部分區塊，此時應保留後端的分段資訊
 */
function applySplitMeta(orders: WorkOrder[]): WorkOrder[] {
  const groups = new Map<string, WorkOrder[]>()

  for (const o of orders) {
    const key = `${o.orderId}__${o.productId}`
    const arr = groups.get(key)
    if (arr) arr.push(o)
    else groups.set(key, [o])
  }

  const rebuilt: WorkOrder[] = []
  for (const [, group] of groups) {
    const sorted = [...group].sort((a, b) => {
      // 先依 startHour 排序，若 startHour 相同再依 id 以確保穩定
      if (a.startHour !== b.startHour) return a.startHour - b.startHour
      return String(a.id).localeCompare(String(b.id))
    })
    const total = sorted.length
    
    // 如果後端已經標記為分段，保留後端的 totalSplits 資訊
    const backendTotalSplits = sorted[0]?.totalSplits
    const actualTotal = backendTotalSplits && backendTotalSplits > total ? backendTotalSplits : total
    const isSplit = actualTotal > 1
    
    for (let i = 0; i < total; i += 1) {
      const order = sorted[i]
      // 保留後端的 splitPart，如果沒有則按順序分配
      const splitPart = order.splitPart ?? (isSplit ? i + 1 : undefined)
      
      rebuilt.push({
        ...order,
        isSplit,
        splitPart,
        totalSplits: isSplit ? actualTotal : undefined,
      })
    }
  }

  // 依 machineId / scheduledDate / startHour 排序，維持畫面一致
  return rebuilt.sort((a, b) => {
    const m = String(a.machineId).localeCompare(String(b.machineId))
    if (m !== 0) return m
    const d = String(a.scheduledDate).localeCompare(String(b.scheduledDate))
    if (d !== 0) return d
    if (a.startHour !== b.startHour) return a.startHour - b.startHour
    return String(a.id).localeCompare(String(b.id))
  })
}

type DowntimeSlot = {
  id: string
  machineId: string
  startHour: number
  endHour: number
}

type ViewMode = 'machine' | 'order'

type DragState = {
  order: WorkOrder
  offsetX: number
  initialX: number
}

type PanState = {
  startX: number
  startY: number
  scrollLeft: number
  scrollTop: number
}

export default function SchedulingPage() {
  const timeline = useTimeline()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const timelineRowsScrollRef = useRef<HTMLDivElement>(null)
  
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0])
  const [viewMode, setViewMode] = useState<ViewMode>('machine')
  const [filteredStatus, setFilteredStatus] = useState<'all' | 'running' | 'idle'>('all')
  const [orders, setOrders] = useState<Order[]>([])
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [snapLineX, setSnapLineX] = useState<number | null>(null)
  const [dragTooltip, setDragTooltip] = useState<{ x: number; y: number; start: string; end: string; duration: string } | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [panState, setPanState] = useState<PanState | null>(null)
  const [dragPreview, setDragPreview] = useState<{ startHour: number; endHour: number; machineId: string } | null>(null)
  const [isOffWorkConflict, setIsOffWorkConflict] = useState(false)
  
  // 機台和區域狀態
  const [machines, setMachines] = useState<{ machine_id: string; area: string }[]>([])
  const [areas, setAreas] = useState<string[]>([])
  const [selectedArea, setSelectedArea] = useState<string>('all')
  
  const MACHINE_ROW_HEIGHT = 60
  const MACHINE_LABEL_WIDTH = 120
  
  // Downtime slots state
  const [downtimeSlots, setDowntimeSlots] = useState<DowntimeSlot[]>([])
  
  // Work calendar state (工作日曆 - 每天的工時)
  const [workCalendar, setWorkCalendar] = useState<Map<string, { work_hours: number; start_time: string }>>(new Map())
  
  // Downtime form state
  const [showDowntimeForm, setShowDowntimeForm] = useState(false)
  const [downtimeForm, setDowntimeForm] = useState({
    machineId: 'A01',
    startTime: '08:00',
    endTime: '09:00'
  })
  
  // 排程配置狀態
  const [showSchedulingConfig, setShowSchedulingConfig] = useState(false)
  const [schedulingConfig, setSchedulingConfig] = useState({
    merge_enabled: true,
    merge_window_weeks: 2,
    time_threshold_pct: 10,
    reschedule_all: false
  })
  const [isScheduling, setIsScheduling] = useState(false)
  
  // Cross-day scheduling dialog state (跨日排程確認對話框)
  const [showCrossDayDialog, setShowCrossDayDialog] = useState(false)
  const [pendingCrossDaySchedule, setPendingCrossDaySchedule] = useState<{
    order: WorkOrder;
    newStartHour: number;
    newEndHour: number;
    targetMachine: string;
  } | null>(null)
  
  // Fullscreen toggle function for gantt chart only
  const toggleFullscreen = async () => {
    if (!scrollContainerRef.current) return
    
    try {
      if (!document.fullscreenElement) {
        await scrollContainerRef.current.requestFullscreen()
        setIsFullscreen(true)
      } else {
        await document.exitFullscreen()
        setIsFullscreen(false)
      }
    } catch (error) {
      console.error('全螢幕切換失敗:', error)
    }
  }
  
  // Listen for fullscreen changes
  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement)
    }
    
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])
  
  // Load machines and areas on mount
  useEffect(() => {
    const loadMachinesAndAreas = async () => {
      try {
        const [machinesData, areasData] = await Promise.all([
          api.getMachines(),
          api.getAreas()
        ])
        setMachines(machinesData)
        setAreas(areasData.areas)
      } catch (error) {
        console.error('Failed to load machines:', error)
      }
    }
    loadMachinesAndAreas()
  }, [])

  // Load orders from Order Management system
  useEffect(() => {
    const loadOrders = async () => {
      const allOrders = await api.getOrders()
      setOrders(allOrders)
    }
    loadOrders()
  }, [])
  
  // Load downtimes from backend when date changes
  useEffect(() => {
    const loadDowntimes = async () => {
      try {
        const downtimes = await api.getDowntimes(selectedDate)
        const formattedDowntimes: DowntimeSlot[] = downtimes.map(dt => ({
          id: dt.id,
          machineId: dt.machine_id,
          startHour: dt.start_hour,
          endHour: dt.end_hour
        }))
        setDowntimeSlots(formattedDowntimes)
      } catch (error) {
        console.error('Failed to load downtimes:', error)
      }
    }
    loadDowntimes()
  }, [selectedDate])
  
  // Load work calendar data (工作日曆)
  useEffect(() => {
    const loadWorkCalendar = async () => {
      try {
        // 載入當前月份的工作日曆
        const date = new Date(selectedDate)
        const year = date.getFullYear()
        const month = date.getMonth() + 1
        
        const calendarData = await api.getWorkCalendar(year, month)
        const map = new Map<string, { work_hours: number; start_time: string }>()
        
        calendarData.forEach((day: any) => {
          map.set(day.work_date, {
            work_hours: day.work_hours,
            start_time: day.start_time
          })
        })
        
        setWorkCalendar(map)
        console.log('📅 已載入工作日曆:', map.size, '筆資料')
      } catch (error) {
        console.error('Failed to load work calendar:', error)
      }
    }
    loadWorkCalendar()
  }, [selectedDate])
  
  // Filter machines by selected area
  const filteredMachines = selectedArea === 'all' 
    ? machines 
    : machines.filter(m => m.area === selectedArea)
  
  // Manual work orders state (for drag-and-drop modifications)
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  
  // Load scheduled components from backend when date changes
  useEffect(() => {
    const loadScheduledComponents = async () => {
      try {
        const { schedules } = await api.getScheduledComponents(selectedDate)
        console.log('📊 載入已排程資料:', schedules.length, '筆')
        
        // Convert backend schedules to WorkOrder format
        let scheduledWorkOrders: WorkOrder[] = schedules.map(schedule => ({
          id: schedule.id,
          orderId: schedule.orderId,
          productId: schedule.productId,
          machineId: schedule.machineId,
          startHour: schedule.startHour,
          endHour: schedule.endHour,
          scheduledDate: schedule.scheduledDate, // 包含排程日期
          status: schedule.status as 'running' | 'idle',
          aiLocked: schedule.aiLocked,
          isSplit: schedule.isSplit,
          splitPart: schedule.splitPart,
          totalSplits: schedule.totalSplits,
          originalId: schedule.id // 記錄原始 ID，用於儲存時刪除舊資料
        }))
        
        // 重新計算分段資訊，避免後端 isSplit/total_sequences 不一致造成「無法同步拖動」
        setWorkOrders(applySplitMeta(scheduledWorkOrders))
      } catch (error) {
        console.error('Failed to load scheduled components:', error)
      }
    }
    loadScheduledComponents()
  }, [selectedDate])
  
  // Helper: Convert HH:MM string to decimal hours
  const timeStringToHours = (timeStr: string): number => {
    const [hours, minutes] = timeStr.split(':').map(Number)
    return hours + minutes / 60
  }
  
  // Helper: 計算指定日期的下班時間 (以時間軸座標系統，從8開始)
  const getOffWorkHour = (dateStr: string): number => {
    const dayInfo = workCalendar.get(dateStr)
    if (!dayInfo) {
      // 如果沒有資料，預設 16 小時工時 + 1 小時休息（8:00 - 25:00）
      return 8 + 16 + 1 // 時間軸座標: 25
    }
    
    // 解析開始時間 (預設 08:00)
    const startHour = timeStringToHours(dayInfo.start_time)
    
    // 如果工時為0（休息日），下班時間 = 開始時間（不加休息時間）
    if (dayInfo.work_hours === 0) {
      console.log(`📅 ${dateStr}: 休息日，工時=0，下班時間 = ${startHour}`)
      return startHour
    }
    
    // 計算下班時間 = 開始時間 + 工時 + 1小時休息時間
    const offWorkTime = startHour + dayInfo.work_hours + 1
    
    console.log(`📅 ${dateStr}: 開始 ${dayInfo.start_time} + ${dayInfo.work_hours}小時 + 1小時休息 = 下班時間 ${offWorkTime}`)
    
    return offWorkTime
  }
  
  // Helper: 生成下班時間遮罩區域
  const getOffWorkOverlays = useMemo(() => {
    const overlays: { startHour: number; endHour: number }[] = []
    
    // 當前選擇日期的下班時間
    const currentDayEnd = getOffWorkHour(selectedDate)
    if (currentDayEnd < 32) { // 32 是時間軸結束（隔天8點）
      overlays.push({
        startHour: currentDayEnd,
        endHour: 32
      })
    }
    
    // 如果時間軸跨日（8點開始到隔天8點），還需要處理前半段（隔天的上班前時間）
    const nextDay = new Date(selectedDate)
    nextDay.setDate(nextDay.getDate() + 1)
    const nextDayStr = nextDay.toISOString().split('T')[0]
    const nextDayStart = 8 // 隔天 8:00 開始上班（時間軸座標: 8）
    const nextDayEnd = getOffWorkHour(nextDayStr)
    
    // 時間軸顯示到隔天8點（座標24-32對應隔天0:00-8:00）
    // 如果隔天8點前就下班了，需要標記
    if (nextDayEnd < nextDayStart) {
      // 這種情況比較特殊：隔天不上班或工時為0
      // 在時間軸上 24-32 區間（隔天 0:00-8:00）全部標記為下班
      overlays.push({
        startHour: 24, // 隔天 0:00
        endHour: 32    // 隔天 8:00
      })
    }
    
    return overlays
  }, [selectedDate, workCalendar])
  
  // Helper: Convert decimal hours to HH:MM string
  const hoursToTimeString = (hours: number): string => {
    const h = Math.floor(hours)
    const m = Math.round((hours - h) * 60)
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  }
  
  const getStatusColor = (status: string) => {
    const colors = {
      running: '#22c55e',
      idle: '#eab308'
    }
    return colors[status as keyof typeof colors] || '#9aa4b2'
  }
  
  const getStatusLabel = (status: string) => {
    const labels = { running: '生產中', idle: '待機' }
    return labels[status as keyof typeof labels] || status
  }
  
  const filteredOrders = workOrders.filter((wo) => {
    // Filter by status
    if (filteredStatus !== 'all' && wo.status !== filteredStatus) {
      return false
    }
    
    // 篩選：只顯示當前選擇日期的排程區塊
    // workOrders 從 API 載入時已經包含 scheduledDate 欄位
    // 這個欄位來自後端的區塊分割邏輯，每個區塊都有自己的日期
    if (wo.scheduledDate && wo.scheduledDate !== selectedDate) {
      return false
    }
    
    return true
  })
  
  // Format time for display
  const formatTime = (hour: number): string => {
    let h = Math.floor(hour)
    const m = Math.round((hour - h) * 60)
    // 處理超過24小時的情況
    if (h >= 24) {
      h = h % 24
    }
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  }
  
  // Format duration for display
  const formatDuration = (hours: number): string => {
    const h = Math.floor(hours)
    const m = Math.round((hours - h) * 60)
    if (h > 0 && m > 0) return `${h}h ${m}m`
    if (h > 0) return `${h}h`
    return `${m}m`
  }
  
  // Handle mouse drag start
  const handleCardMouseDown = (e: React.MouseEvent, order: WorkOrder) => {
    e.preventDefault()
    if (!timelineRef.current) return
    
    const rect = timelineRef.current.getBoundingClientRect()
    // 在全螢幕模式下，機台標籤列可能不在視口內，需要動態計算
    const labelsColumn = document.querySelector(`.${styles.machineLabelsColumn}`) as HTMLElement
    const labelWidth = labelsColumn ? labelsColumn.offsetWidth : MACHINE_LABEL_WIDTH
    const mouseX = e.clientX - rect.left
    
    // 以目前 workOrders 的分組結果判斷是否為分段，避免後端 isSplit 不一致導致同步拖動失效
    const groupCount = workOrders.filter(
      wo => wo.orderId === order.orderId && wo.productId === order.productId
    ).length
    const isSplit = groupCount > 1

    setDragState({
      order: {
        ...order,
        isSplit,
        totalSplits: isSplit ? groupCount : undefined
      },
      offsetX: mouseX - timeline.timeToX(order.startHour),
      initialX: mouseX
    })
  }
  
  // Handle mouse move during drag
  useEffect(() => {
    if (!dragState) return
    
    const handleMouseMove = (e: MouseEvent) => {
      if (!timelineRef.current || !scrollContainerRef.current) return
      
      const rect = timelineRef.current.getBoundingClientRect()
      const containerRect = scrollContainerRef.current.getBoundingClientRect()
      // 在全螢幕模式下，機台標籤列可能不在視口內，需要動態計算
      const labelsColumn = document.querySelector(`.${styles.machineLabelsColumn}`) as HTMLElement
      const labelWidth = labelsColumn ? labelsColumn.offsetWidth : MACHINE_LABEL_WIDTH
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      
      // Calculate new start time
      const rawStartTime = timeline.xToTime(mouseX - dragState.offsetX)
      const duration = dragState.order.endHour - dragState.order.startHour
      
      // Snap to grid for precision
      const snappedStart = timeline.snapToGrid(rawStartTime)
      
      // Clamp to valid range
      const clampedStart = Math.max(timeline.t0, Math.min(timeline.t1 - duration, snappedStart))
      const clampedEnd = clampedStart + duration
      
      // Update snap line to snapped position
      const snappedX = timeline.timeToX(clampedStart)
      setSnapLineX(snappedX)
      
      // Determine target machine based on mouse position
      const machineIndex = Math.floor(mouseY / MACHINE_ROW_HEIGHT)
      const targetMachine = filteredMachines[machineIndex]?.machine_id || dragState.order.machineId
      
      // Update drag preview for live card movement
      setDragPreview({
        startHour: clampedStart,
        endHour: clampedEnd,
        machineId: targetMachine
      })
      
      // Check if dragging overlaps with off-work hours (檢測是否與下班時間重疊)
      const hasOffWorkOverlap = getOffWorkOverlays.some(overlay => {
        // Check if the work order overlaps with this off-work period
        return clampedStart < overlay.endHour && clampedEnd > overlay.startHour
      })
      setIsOffWorkConflict(hasOffWorkOverlap)
      
      // Update tooltip with snapped values - 使用相對於 boardContainer 的座標
      setDragTooltip({
        x: e.clientX - containerRect.left,
        y: e.clientY - containerRect.top,
        start: formatTime(clampedStart),
        end: formatTime(clampedEnd),
        duration: formatDuration(duration)
      })
    }
    
    const handleMouseUp = (e: MouseEvent) => {
      if (!timelineRef.current || !dragState) return
      
      const rect = timelineRef.current.getBoundingClientRect()
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      
      // Calculate new start time with snapping
      const rawStartTime = timeline.xToTime(mouseX - dragState.offsetX)
      const snappedStart = timeline.snapToGrid(rawStartTime)
      const duration = dragState.order.endHour - dragState.order.startHour
      
      // Determine target machine
      const machineIndex = Math.floor(mouseY / MACHINE_ROW_HEIGHT)
      const targetMachine = filteredMachines[machineIndex]?.machine_id || dragState.order.machineId
      
      // Default behavior (Fixed Duration)
      let clampedStart = Math.max(timeline.t0, Math.min(timeline.t1 - duration, snappedStart))
      let clampedEnd = clampedStart + duration
      
      // Special handling for Split Parts (Override clampedStart/clampedEnd)
      let isSplitAdjustment = false
      if (dragState.order.isSplit && dragState.order.totalSplits && dragState.order.totalSplits > 1) {
         if (dragState.order.splitPart === 1) {
             // Head: End is fixed to next off-work
             isSplitAdjustment = true
             
             // Allow start to be anywhere (within reason)
             clampedStart = Math.max(timeline.t0, Math.min(timeline.t1, snappedStart))
             
             // Find off-work after clampedStart
             const validOffWork = getOffWorkOverlays
                .filter(o => o.startHour > clampedStart)
                .sort((a, b) => a.startHour - b.startHour)[0]
             const offWork = validOffWork ? validOffWork.startHour : 24
             
             clampedEnd = offWork
             // Ensure valid duration
             if (clampedEnd <= clampedStart) clampedStart = clampedEnd - 0.5
             
         } else if (dragState.order.splitPart === dragState.order.totalSplits) {
             // Tail: Start is fixed to work-start (e.g. 8:00)
             isSplitAdjustment = true
             
             const workDayStart = 8
             // Find off-work for this day
             const currentDayOffWork = getOffWorkOverlays.find(o => 
                workDayStart < o.startHour && o.startHour <= 32
             )
             const offWork = currentDayOffWork ? currentDayOffWork.startHour : 24
             
             // The user dragged the card to a new position. 
             // We interpret the END of the dragged card as the desired end time.
             const intendedEnd = snappedStart + duration
             
             clampedStart = workDayStart
             clampedEnd = Math.min(intendedEnd, offWork)
             
             if (clampedEnd <= clampedStart) clampedEnd = clampedStart + 0.5
         }
      }

      // Check for downtime conflicts
      const hasDowntimeConflict = downtimeSlots.some(slot =>
        slot.machineId === targetMachine &&
        slot.startHour < clampedEnd &&
        slot.endHour > clampedStart
      )
      
      // Check for work order conflicts
      const hasOrderConflict = workOrders.some(wo => {
        if (wo.id === dragState.order.id) return false
        if (wo.machineId !== targetMachine) return false

        const overlaps = wo.startHour < clampedEnd && wo.endHour > clampedStart
        if (!overlaps) return false

        // ✅ 同品號 -> 放行（不觸發 overlap 衝突）
        if (wo.productId === dragState.order.productId) return false

        // ❌ 不同品號且重疊 -> 視為衝突
        return true
      })      
      // Check if the new schedule overlaps with off-work hours
      // We restore the check for ALL cases to ensure safety.
      // The split adjustment logic above aligns exactly to boundaries, so it shouldn't trigger false positives.
      const hasOffWorkOverlap = getOffWorkOverlays.some(overlay => {
        // Use a small epsilon to avoid floating point issues at boundaries
        // e.g. 17.0 < 17.0 is false, but 17.0001 < 17.0 is false.
        // If clampedEnd is 17.0 and overlay.startHour is 17.0, we want NO overlap.
        // If clampedEnd is 17.1, we want overlap.
        return clampedStart < overlay.endHour && clampedEnd > (overlay.startHour + 0.001)
      })
      
      if (!hasDowntimeConflict && !hasOrderConflict) {
        if (hasOffWorkOverlap) {
          // Show cross-day scheduling confirmation dialog (顯示跨日排程確認對話框)
          setPendingCrossDaySchedule({
            order: dragState.order,
            newStartHour: clampedStart,
            newEndHour: clampedEnd,
            targetMachine
          })
          setShowCrossDayDialog(true)
        } else {
          // Normal schedule update (正常排程更新)
          
          // Check if this is a split order that needs synchronized adjustment
          // (檢查是否為需要同步調整的分割訂單)
          if (dragState.order.isSplit && dragState.order.totalSplits && dragState.order.totalSplits > 1) {
            const { splitPart, totalSplits, orderId, productId } = dragState.order
            
            // 找到同一製令的所有區塊
            const baseBlockId = dragState.order.id.replace(/-\d+$/, '') // 移除 "-1", "-2" 等後綴
            const allParts = workOrders
              .filter(wo => wo.orderId === orderId && wo.productId === productId)
              .sort((a, b) => {
                const ap = a.splitPart ?? 0
                const bp = b.splitPart ?? 0
                if (ap !== bp) return ap - bp
                return a.startHour - b.startHour
              })
            
            if (splitPart === 1) {
              // ========== 拖拉第一段 (Head) ==========
              // 邏輯：第一段結束時間固定為下班時間，拖拉改變開始時間 -> 改變第一段長度 -> 反向改變第二段長度
              
              // 1. 計算當天的下班時間 (第一段的錨點)
              // 這裡需要找到「最接近且大於 clampedStart」的下班時間
              // 假設下班時間是 17:00 (17.0) 或 20:00 (20.0)
              // 如果 clampedStart 是 13:00，我們應該找到 17:00
              
              // 先過濾出所有在 clampedStart 之後的下班時間點
              const validOffWorkOverlays = getOffWorkOverlays
                .filter(overlay => overlay.startHour > clampedStart)
                .sort((a, b) => a.startHour - b.startHour)
              
              // 取第一個作為下班時間，如果沒有則預設為 24:00
              const offWorkHour = validOffWorkOverlays.length > 0 ? validOffWorkOverlays[0].startHour : 24
              
              // 2. 第一段強制填滿到下班時間
              const adjustedEnd = offWorkHour
              
              // 3. 計算第一段的新長度與長度變化
              const originalPart1Duration = dragState.order.endHour - dragState.order.startHour
              const newPart1Duration = adjustedEnd - clampedStart
              const durationChange = newPart1Duration - originalPart1Duration // 正數=變長(往左拉)，負數=變短(往右拉)
              
              // 4. 更新所有相關區塊
              const lastPart = allParts[allParts.length - 1]
              
              setWorkOrders(prev => prev.map(wo => {
                // 檢查是否為同一組分割訂單 (移除 isSplit 檢查，因為後端可能導致 isSplit 狀態不一致)
                const isGroupMember = wo.orderId === orderId && wo.productId === productId;
                
                if (wo.id === dragState.order.id) {
                  // 更新第一段：開始時間=拖拉位置，結束時間=下班時間，機台=目標機台
                  return { ...wo, machineId: targetMachine, startHour: clampedStart, endHour: adjustedEnd, isModified: true }
                } else if (lastPart && wo.id === lastPart.id) {
                  // 更新最後一段：開始時間不變(08:00)，結束時間根據長度變化調整，機台=目標機台
                  // 前段變長 -> 後段變短；前段變短 -> 後段變長
                  const originalPart2Duration = wo.endHour - wo.startHour
                  const newPart2Duration = originalPart2Duration - durationChange
                  
                  let newEndHour = wo.startHour + 0.1;
                  if (newPart2Duration > 0.1) {
                    newEndHour = wo.startHour + newPart2Duration;
                  }
                  
                  return { ...wo, machineId: targetMachine, endHour: newEndHour, isModified: true }
                } else if (isGroupMember) {
                  // 其他中間段：只更新機台
                  return { ...wo, machineId: targetMachine, isModified: true }
                }
                return wo
              }))
            } else if (splitPart === totalSplits) {
              // ========== 拖拉最後一段 (Tail) ==========
              // 邏輯：最後一段開始時間固定為上班時間，拖拉改變結束時間 -> 改變最後一段長度 -> 反向改變第一段長度
              
              // 1. 找到當天的上班時間 (最後一段的錨點)
              const workDayStart = 8
              
              // 2. 找到當天的下班時間 (限制拖拉範圍)
              const currentDayOffWork = getOffWorkOverlays.find(overlay => 
                workDayStart < overlay.startHour && overlay.startHour <= 32
              )
              const offWorkHour = currentDayOffWork ? currentDayOffWork.startHour : 24
              
              // 3. 最後一段強制從上班時間開始
              const adjustedStart = workDayStart
              const adjustedEnd = Math.min(clampedEnd, offWorkHour)
              
              // 4. 計算最後一段的新長度與長度變化
              const originalPart2Duration = dragState.order.endHour - dragState.order.startHour
              const newPart2Duration = adjustedEnd - adjustedStart
              const durationChange = newPart2Duration - originalPart2Duration // 正數=變長(往右拉)，負數=變短(往左拉)
              
              // 5. 更新所有相關區塊
              const firstPart = allParts[0]
              
              setWorkOrders(prev => prev.map(wo => {
                // 檢查是否為同一組分割訂單 (移除 isSplit 檢查)
                const isGroupMember = wo.orderId === orderId && wo.productId === productId;

                if (wo.id === dragState.order.id) {
                  // 更新最後一段：開始時間=上班時間，結束時間=拖拉位置，機台=目標機台
                  return { ...wo, machineId: targetMachine, startHour: adjustedStart, endHour: adjustedEnd, isModified: true }
                } else if (firstPart && wo.id === firstPart.id) {
                  // 更新第一段：結束時間不變(下班時間)，開始時間根據長度變化調整，機台=目標機台
                  // 後段變長 -> 前段變短(開始時間延後)；後段變短 -> 前段變長(開始時間提前)
                  
                  // 找到第一段的下班時間(結束錨點)
                  const firstOffWorkBoundary = getOffWorkOverlays.find(overlay => 
                    wo.startHour < overlay.startHour && overlay.startHour <= 32
                  )
                  const firstOffWorkHour = firstOffWorkBoundary ? firstOffWorkBoundary.startHour : 24
                  
                  const originalPart1Duration = wo.endHour - wo.startHour
                  const newPart1Duration = originalPart1Duration - durationChange
                  
                  let newStartHour = firstOffWorkHour - 0.1;
                  if (newPart1Duration > 0.1) {
                    newStartHour = firstOffWorkHour - newPart1Duration;
                  }
                  
                  return { 
                    ...wo, 
                    machineId: targetMachine,
                    startHour: newStartHour,
                    endHour: firstOffWorkHour, 
                    isModified: true 
                  }
                } else if (isGroupMember) {
                  // 其他中間段：只更新機台
                  return { ...wo, machineId: targetMachine, isModified: true }
                }
                return wo
              }))
            } else {
              // 中間段 - 更新所有相關區塊的機台
              setWorkOrders(prev => prev.map(wo => {
                const isGroupMember = wo.orderId === orderId && wo.productId === productId;
                if (isGroupMember) {
                   // 如果是拖拉中間段，我們假設只改變機台，不改變時間結構
                   // 或者如果需要改變時間，這裡需要更複雜的邏輯
                   // 目前先實作：拖拉中間段 -> 整組換機台，時間平移(如果有的話)
                   // 但因為中間段通常是滿的，所以只換機台比較合理
                   
                   // 如果是當前拖拉的區塊，應用拖拉的時間 (雖然中間段通常是滿的，但允許微調?)
                   // 為了保持簡單且符合 "連動" 的直覺，拖拉中間段通常意味著 "整組換機台"
                   return { ...wo, machineId: targetMachine, isModified: true }
                }
                return wo
              }))
            }
          } else {
            // Regular single order update (一般單一訂單更新)
            // 單一訂單也應該自動填滿到下班時間
            const currentDayOffWork = getOffWorkOverlays.find(overlay => 
              clampedStart < overlay.startHour && overlay.startHour <= 32
            )
            const offWorkHour = currentDayOffWork ? currentDayOffWork.startHour : 24
            const adjustedEnd = Math.min(clampedEnd, offWorkHour)
            
            setWorkOrders(prev => prev.map(wo =>
              wo.id === dragState.order.id
                ? { ...wo, machineId: targetMachine, startHour: clampedStart, endHour: adjustedEnd, isModified: true }
                : wo
            ))
          }
        }
      }
      
      // Clear drag state
      setDragState(null)
      setSnapLineX(null)
      setDragTooltip(null)
      setDragPreview(null)
      setIsOffWorkConflict(false)
    }
    
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragState, timeline, machines, downtimeSlots])
  
  // Handle right-click pan (視角移動)
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    
    const handleContextMenu = (e: MouseEvent) => {
      e.preventDefault() // 阻止右鍵選單
    }
    
    const handleMouseDown = (e: MouseEvent) => {
      if (e.button === 2) { // 右鍵
        e.preventDefault()
        
        // 獲取實際可滾動的元素
        const timelineRowsScroll = document.getElementById('timeline-rows-scroll') as HTMLElement
        const timeAxisHeader = container.querySelector(`.${styles.timeAxisHeader}`) as HTMLElement
        
        if (timelineRowsScroll) {
          setPanState({
            startX: e.clientX,
            startY: e.clientY,
            scrollLeft: timelineRowsScroll.scrollLeft,
            scrollTop: timelineRowsScroll.scrollTop
          })
          container.style.cursor = 'grabbing'
        }
      }
    }
    
    container.addEventListener('contextmenu', handleContextMenu)
    container.addEventListener('mousedown', handleMouseDown)
    
    return () => {
      container.removeEventListener('contextmenu', handleContextMenu)
      container.removeEventListener('mousedown', handleMouseDown)
    }
  }, [])
  
  // Handle pan move and release
  useEffect(() => {
    if (!panState) return
    
    const handleMouseMove = (e: MouseEvent) => {
      if (!scrollContainerRef.current) return
      
      const deltaX = e.clientX - panState.startX
      const deltaY = e.clientY - panState.startY
      
      // 獲取實際可滾動的元素
      const timelineRowsScroll = document.getElementById('timeline-rows-scroll') as HTMLElement
      const timeAxisHeader = scrollContainerRef.current.querySelector(`.${styles.timeAxisHeader}`) as HTMLElement
      const machineLabelsScroll = document.getElementById('machine-labels-scroll') as HTMLElement
      
      if (timelineRowsScroll) {
        timelineRowsScroll.scrollLeft = panState.scrollLeft - deltaX
        timelineRowsScroll.scrollTop = panState.scrollTop - deltaY
        
        // 同步其他滾動區域
        if (timeAxisHeader) {
          timeAxisHeader.scrollLeft = panState.scrollLeft - deltaX
        }
        if (machineLabelsScroll) {
          machineLabelsScroll.scrollTop = panState.scrollTop - deltaY
        }
      }
    }
    
    const handleMouseUp = () => {
      if (scrollContainerRef.current) {
        scrollContainerRef.current.style.cursor = ''
      }
      setPanState(null)
    }
    
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [panState])
  
  // Handle zoom and scroll with mouse wheel
  useEffect(() => {
    const container = scrollContainerRef.current
    if (!container) return
    
    const handleWheel = (e: WheelEvent) => {
      if (e.shiftKey) {
        // Horizontal scroll with Shift
        e.preventDefault()
        container.scrollLeft += e.deltaY
      } else if (e.ctrlKey || e.metaKey) {
        // Zoom with Ctrl/Cmd
        e.preventDefault()
        const delta = -e.deltaY / 100
        const newZoom = Math.max(0.5, Math.min(6, timeline.zoom + delta))
        timeline.setZoom(newZoom)
      }
      // Otherwise let default vertical scroll happen naturally
    }
    
    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => container.removeEventListener('wheel', handleWheel)
  }, [timeline])

  // Handle horizontal scroll with Shift+Wheel on timeline rows
  useEffect(() => {
    const container = timelineRowsScrollRef.current
    if (!container) return

    const handleWheel = (e: WheelEvent) => {
      if (e.shiftKey) {
        e.preventDefault()
        container.scrollLeft += e.deltaY
        // Sync with header
        const header = container.previousElementSibling as HTMLElement
        if (header) {
          header.scrollLeft = container.scrollLeft
        }
      }
    }

    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => container.removeEventListener('wheel', handleWheel)
  }, [])
  
  // Keyboard shortcuts for navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const container = scrollContainerRef.current
      if (!container) return
      
      const scrollAmount = 100
      
      switch(e.key) {
        case 'ArrowLeft':
          e.preventDefault()
          container.scrollLeft -= scrollAmount
          break
        case 'ArrowRight':
          e.preventDefault()
          container.scrollLeft += scrollAmount
          break
        case 'ArrowUp':
          e.preventDefault()
          container.scrollTop -= scrollAmount
          break
        case 'ArrowDown':
          e.preventDefault()
          container.scrollTop += scrollAmount
          break
        case 'Home':
          e.preventDefault()
          container.scrollLeft = 0
          break
        case 'End':
          e.preventDefault()
          container.scrollLeft = container.scrollWidth
          break
      }
    }
    
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])
  
  // Determine if we should show compact cards
  const isCompactMode = timeline.zoom >= 2
  
  // Handle downtime form submit
  const handleAddDowntime = async () => {
    const startHour = timeStringToHours(downtimeForm.startTime)
    const endHour = timeStringToHours(downtimeForm.endTime)
    
    if (endHour <= startHour) {
      alert('結束時間必須大於開始時間')
      return
    }
    
    try {
      // 儲存到後端資料庫
      await api.createDowntime({
        machine_id: downtimeForm.machineId,
        start_hour: startHour,
        end_hour: endHour,
        date: selectedDate,
        reason: '維護'
      })
      
      // 重新載入停機時段
      const downtimes = await api.getDowntimes(selectedDate)
      const formattedDowntimes: DowntimeSlot[] = downtimes.map(dt => ({
        id: dt.id,
        machineId: dt.machine_id,
        startHour: dt.start_hour,
        endHour: dt.end_hour
      }))
      setDowntimeSlots(formattedDowntimes)
      
      setShowDowntimeForm(false)
      setDowntimeForm({
        machineId: filteredMachines.length > 0 ? filteredMachines[0].machine_id : 'A01',
        startTime: '08:00',
        endTime: '09:00'
      })
    } catch (error) {
      console.error('Failed to create downtime:', error)
      alert('新增停機時段失敗，請確認後端服務已啟動')
    }
  }
  
  // Handle delete downtime
  const handleDeleteDowntime = async (id: string) => {
    try {
      await api.deleteDowntime(id)
      // 重新載入停機時段
      const downtimes = await api.getDowntimes(selectedDate)
      const formattedDowntimes: DowntimeSlot[] = downtimes.map(dt => ({
        id: dt.id,
        machineId: dt.machine_id,
        startHour: dt.start_hour,
        endHour: dt.end_hour
      }))
      setDowntimeSlots(formattedDowntimes)
    } catch (error) {
      console.error('Failed to delete downtime:', error)
      alert('刪除停機時段失敗')
    }
  }
  
  // Handle 排程
  const handleScheduling = async () => {
    setIsScheduling(true)
    
    try {
      // 調用後端排程引擎 API
      const result = await api.runScheduling({
        order_ids: undefined, // 排程所有待排程訂單
        merge_enabled: schedulingConfig.merge_enabled,
        merge_window_weeks: schedulingConfig.merge_window_weeks,
        time_threshold_pct: schedulingConfig.time_threshold_pct,
        reschedule_all: schedulingConfig.reschedule_all
      })
      
      if (result.success) {
        // 排程完成後，重新從後端載入排程結果
        // 後端已經處理了區塊分割和時間計算
        const { schedules } = await api.getScheduledComponents(selectedDate)
        const scheduledWorkOrders: WorkOrder[] = schedules.map(schedule => ({
          id: schedule.id,
          orderId: schedule.orderId,
          productId: schedule.productId,
          machineId: schedule.machineId,
          startHour: schedule.startHour,
          endHour: schedule.endHour,
          scheduledDate: schedule.scheduledDate,
          status: schedule.status as 'running' | 'idle',
          aiLocked: schedule.aiLocked
        }))
        
        // 重新計算分段資訊，避免後端 isSplit/total_sequences 不一致造成「無法同步拖動」
        setWorkOrders(applySplitMeta(scheduledWorkOrders))
        setShowSchedulingConfig(false)
        
        // 顯示排程完成通知
        const successMsg = [
          `✅ 排程完成！`,
          ``,
          `📊 統計資訊：`,
          `- 總訂單數: ${result.total_mos}`,
          `- 成功排程: ${result.scheduled_mos.length}`,
          `- 失敗訂單: ${result.failed_mos.length}`,
          `- 準時完成: ${result.on_time_count}`,
          `- 延遲訂單: ${result.late_count}`,
          ``,
          `⏱️ 執行時間: ${result.execution_time_seconds.toFixed(2)}秒`,
          ``,
          result.change_log.length > 0 ? `📝 變更記錄：\n${result.change_log.slice(0, 5).join('\n')}` : ''
        ].join('\n')
        
        alert(successMsg)
      } else {
        alert(`❌ 排程失敗：\n${result.message}`)
      }
      
    } catch (error) {
      console.error('Scheduling error:', error)
      alert(`排程錯誤: ${error instanceof Error ? error.message : '未知錯誤'}`)
    } finally {
      setIsScheduling(false)
    }
  }
  
  return (
    <div className="scheduling-page">
      {/* Toolbar */}
      <div className="scheduling-toolbar" style={{ position: 'relative' }}>
        {/* Fullscreen button */}
        <button
          onClick={toggleFullscreen}
          className={styles.fullscreenButton}
          title={isFullscreen ? '退出全螢幕 (ESC)' : '展開甘特圖'}
        >
          {isFullscreen ? '⛶' : '⛶'}
          <span className={styles.fullscreenButtonText}>
            {isFullscreen ? '縮小' : '展開'}
          </span>
        </button>
        
        <div className="toolbar-section">
          <label>日期
            <input type="date" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} />
          </label>
        </div>
        
        <div className="toolbar-section">
          <button
            onClick={() => setViewMode('machine')}
            className={viewMode === 'machine' ? 'active' : ''}
          >
            機台視角
          </button>
          <button
            onClick={() => setViewMode('order')}
            className={viewMode === 'order' ? 'active' : ''}
          >
            訂單視角
          </button>
        </div>
        
        <div className="toolbar-section zoom-controls">
          <label>縮放</label>
          <input
            type="range"
            min="0.5"
            max="6"
            step="0.1"
            value={timeline.zoom}
            onChange={(e) => timeline.setZoom(parseFloat(e.target.value))}
            className="zoom-slider"
          />
          <span className="zoom-value">{timeline.zoom.toFixed(1)}x</span>
          <button onClick={() => timeline.setZoom(1)} className="zoom-reset-btn">重置</button>
          <span className="snap-indicator" style={{ 
            fontSize: 10, 
            color: 'rgba(255,255,255,0.5)',
            marginLeft: 8,
            padding: '4px 8px',
            background: 'rgba(30,160,233,0.1)',
            borderRadius: 4,
            border: '1px solid rgba(30,160,233,0.2)'
          }}>
            貼齊: {timeline.getSnapInterval() >= 1 
              ? `${Math.round(timeline.getSnapInterval())}hr` 
              : `${Math.round(timeline.getSnapInterval() * 60)}min`}
          </span>
        </div>
        
        <div className="toolbar-section">
          <button 
            className="primary-btn"
            onClick={() => setShowSchedulingConfig(true)}
            disabled={isScheduling}
            style={{
              opacity: isScheduling ? 0.6 : 1,
              cursor: isScheduling ? 'not-allowed' : 'pointer'
            }}
          >
            {isScheduling ? '⏳ 排程中...' : '🚀 開始排程'}
          </button>
          
          <button
            onClick={async () => {
              try {
                // 1. 找出所有被修改過的訂單
                const modifiedOrders = workOrders.filter(wo => wo.isModified)
                
                if (modifiedOrders.length === 0) {
                  alert('沒有需要儲存的變更')
                  return
                }

                // 2. 收集需要刪除的原始區塊 ID (originalId)
                // 這些是我們這次操作要「取代」掉的舊資料
                const deletedIds = Array.from(new Set(
                  modifiedOrders
                    .map(wo => wo.originalId || wo.id) // 如果沒有 originalId，就用 id (表示沒被分割過)
                    .filter(id => !id.startsWith('split-')) // 排除掉新產生的 split ID (因為資料庫還沒有)
                ))

                // 3. 準備要新增/更新的區塊資料
                // 注意：這裡只傳送「被修改的訂單」的新狀態
                // 如果一個訂單被分割成兩塊，這兩塊都會在 modifiedOrders 裡
                const updates = modifiedOrders.map(wo => ({
                  id: wo.id,
                  orderId: wo.orderId,
                  productId: wo.productId,
                  startHour: wo.startHour,
                  endHour: wo.endHour,
                  machineId: wo.machineId,
                  scheduledDate: selectedDate, 
                  status: wo.status,
                  aiLocked: wo.aiLocked,
                  isModified: wo.isModified // 傳送修改標記
                }))

                // 呼叫後端 API
                const result = await api.updateScheduledComponents(updates, deletedIds)
                
                if (result.success) {
                  alert(`✅ 已成功儲存 ${result.updated_count} 筆排程調整`)
                  // 清除 isModified 標記
                  setWorkOrders(prev => prev.map(wo => ({ ...wo, isModified: false })))
                } else {
                  alert('❌ 儲存部分失敗，請查看控制台日誌')
                  console.error('Save errors:', result.errors)
                }
                
              } catch (error) {
                console.error('儲存失敗:', error)
                alert('❌ 儲存失敗: ' + (error instanceof Error ? error.message : '未知錯誤'))
              }
            }}
            disabled={!workOrders.some(wo => wo.isModified)}
            style={{
              padding: '10px 20px',
              background: !workOrders.some(wo => wo.isModified) ? 'rgba(255,255,255,0.1)' : 'linear-gradient(135deg, #10b981, #059669)',
              border: 'none',
              borderRadius: 8,
              color: '#fff',
              fontSize: 14,
              fontWeight: 600,
              cursor: !workOrders.some(wo => wo.isModified) ? 'not-allowed' : 'pointer',
              opacity: !workOrders.some(wo => wo.isModified) ? 0.5 : 1,
              transition: 'all 0.2s',
              boxShadow: workOrders.some(wo => wo.isModified) ? '0 4px 12px rgba(16,185,129,0.3)' : 'none'
            }}
          >
            💾 儲存排程
          </button>
          
          <button
            onClick={async () => {
              if (confirm('確定要重置所有未儲存的調整嗎？將恢復到後端排程的原始狀態。')) {
                // 重新從後端載入原始排程
                try {
                  const { schedules } = await api.getScheduledComponents(selectedDate)
                  const scheduledWorkOrders: WorkOrder[] = schedules.map(schedule => ({
                    id: schedule.id,
                    orderId: schedule.orderId,
                    productId: schedule.productId,
                    machineId: schedule.machineId,
                    startHour: schedule.startHour,
                    endHour: schedule.endHour,
                    scheduledDate: schedule.scheduledDate,
                    status: schedule.status as 'running' | 'idle',
                    aiLocked: schedule.aiLocked,
                    isSplit: schedule.isSplit,
                    splitPart: schedule.splitPart,
                    totalSplits: schedule.totalSplits,
                    isModified: false
                  }))
                  // 重新計算分段資訊，避免後端 isSplit/total_sequences 不一致造成「無法同步拖動」
                  setWorkOrders(applySplitMeta(scheduledWorkOrders))
                  console.log('✅ 已重置到原始排程')
                } catch (error) {
                  console.error('重置失敗:', error)
                  alert('重置失敗')
                }
              }
            }}
            disabled={workOrders.length === 0 || !workOrders.some(wo => wo.isModified)}
            style={{
              padding: '10px 20px',
              background: (workOrders.length === 0 || !workOrders.some(wo => wo.isModified)) ? 'rgba(255,255,255,0.1)' : 'linear-gradient(135deg, #f59e0b, #d97706)',
              border: 'none',
              borderRadius: 8,
              color: '#fff',
              fontSize: 14,
              fontWeight: 600,
              cursor: (workOrders.length === 0 || !workOrders.some(wo => wo.isModified)) ? 'not-allowed' : 'pointer',
              opacity: (workOrders.length === 0 || !workOrders.some(wo => wo.isModified)) ? 0.5 : 1,
              transition: 'all 0.2s',
              boxShadow: workOrders.some(wo => wo.isModified) ? '0 4px 12px rgba(245,158,11,0.3)' : 'none'
            }}
          >
            🔄 重置調整
          </button>
          
          <button className="urgent-btn">插入急單並重排</button>
          <button 
            onClick={() => setShowDowntimeForm(true)}
            style={{
              padding: '8px 16px',
              background: 'linear-gradient(135deg, #ef4444, #dc2626)',
              border: 'none',
              borderRadius: 8,
              color: '#fff',
              fontWeight: 600,
              cursor: 'pointer',
              fontSize: 14
            }}
          >
            + 新增停機時段
          </button>
        </div>
      </div>
      
      <div className="scheduling-content">
        {/* Left sidebar: filters & legend */}
        <aside className="scheduling-sidebar">
          <div className="filter-section">
            <h3>區域篩選</h3>
            <div className="filter-options">
              <label>
                <input
                  type="radio"
                  name="area"
                  value="all"
                  checked={selectedArea === 'all'}
                  onChange={(e) => setSelectedArea(e.target.value)}
                />
                全部區域
              </label>
              {areas.map((area) => (
                <label key={area}>
                  <input
                    type="radio"
                    name="area"
                    value={area}
                    checked={selectedArea === area}
                    onChange={(e) => setSelectedArea(e.target.value)}
                  />
                  {area}區 ({machines.filter(m => m.area === area).length}台)
                </label>
              ))}
            </div>
          </div>
          
          <div className="filter-section" style={{ marginTop: 20 }}>
            <h3>狀態篩選</h3>
            <div className="filter-options">
              {['all', 'running', 'idle'].map((status) => (
                <label key={status}>
                  <input
                    type="radio"
                    name="status"
                    value={status}
                    checked={filteredStatus === status}
                    onChange={(e) => setFilteredStatus(e.target.value as any)}
                  />
                  {status === 'all' ? '全部' : getStatusLabel(status)}
                </label>
              ))}
            </div>
          </div>
          
          <div className="legend-section">
            <h3>狀態圖例</h3>
            <div className="legend-items">
              {['running', 'idle'].map((status) => (
                <div key={status} className="legend-item">
                  <div
                    className="legend-color"
                    style={{ backgroundColor: getStatusColor(status) }}
                  />
                  <span>{getStatusLabel(status)}</span>
                </div>
              ))}
              <div className="legend-item">
                <div
                  className="legend-color"
                  style={{ backgroundColor: '#ef4444' }}
                />
                <span>停機時段</span>
              </div>
            </div>
          </div>
          
          <div className="downtime-list-section" style={{ marginTop: 24 }}>
            <h3>停機時段列表</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
              {downtimeSlots.length === 0 ? (
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)', padding: 8 }}>
                  無停機時段
                </div>
              ) : (
                downtimeSlots.map(slot => (
                  <div
                    key={slot.id}
                    style={{
                      padding: '8px 12px',
                      background: 'rgba(239,68,68,0.1)',
                      border: '1px solid rgba(239,68,68,0.3)',
                      borderRadius: 6,
                      fontSize: 12,
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center'
                    }}
                  >
                    <div>
                      <div style={{ fontWeight: 600, color: '#ef4444' }}>
                        機台 {slot.machineId}
                      </div>
                      <div style={{ color: 'rgba(255,255,255,0.7)', marginTop: 4 }}>
                        {formatTime(slot.startHour)} - {formatTime(slot.endHour)}
                      </div>
                    </div>
                    <button
                      onClick={() => handleDeleteDowntime(slot.id)}
                      style={{
                        padding: '4px 8px',
                        background: 'rgba(239,68,68,0.2)',
                        border: '1px solid rgba(239,68,68,0.4)',
                        borderRadius: 4,
                        color: '#ef4444',
                        cursor: 'pointer',
                        fontSize: 11
                      }}
                    >
                      刪除
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </aside>
        
        {/* Main: scheduling board */}
        <div className={styles.mainWrapper}>
          <div className={styles.boardContainer} ref={scrollContainerRef}>
            {/* Fixed machine labels column */}
            <div className={styles.machineLabelsColumn}>
              {/* Header */}
              <div className={styles.machineLabelsHeader}>
                機台編號
              </div>
              {/* Machine labels - scrollable */}
              <div 
                id="machine-labels-scroll"
                className={styles.machineLabelsScroll}
                onScroll={(e) => {
                  const timelineScroll = document.getElementById('timeline-rows-scroll')
                  if (timelineScroll) {
                    timelineScroll.scrollTop = e.currentTarget.scrollTop
                  }
                }}
              >
                <div style={{ minHeight: filteredMachines.length * MACHINE_ROW_HEIGHT }}>
                  {filteredMachines.map((machine, index) => (
                    <div
                      key={machine.machine_id}
                      className={styles.machineLabel}
                      style={{ height: MACHINE_ROW_HEIGHT }}
                    >
                      <div className={styles.machineLabelId}>{machine.machine_id}</div>
                      <div className={styles.machineLabelArea}>{machine.area}區</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            
            {/* Scrollable timeline area */}
            <div 
              id="timeline-scroll"
              className={styles.timelineScrollArea}
            >
              {/* Time axis header - fixed */}
              <div className={styles.timeAxisHeader}>
                <div className={styles.timeAxisContent} style={{ width: timeline.totalWidth }}>
                  {/* Vertical grid lines */}
                  {timeline.getTimeMarks().map((mark) => (
                    <div
                      key={`grid-line-${mark.time}`}
                      className={`${styles.gridLine} ${mark.type === 'major' ? styles.gridLineMajor : styles.gridLineMinor}`}
                      style={{ left: mark.x }}
                    />
                  ))}
                  {/* Time labels */}
                  {timeline.getTimeMarks().filter(m => m.type === 'major').map((mark) => (
                    <div
                      key={`mark-${mark.time}`}
                      className={styles.timeLabel}
                      style={{ left: mark.x + 6 }}
                    >
                      {mark.label}
                    </div>
                  ))}
                </div>
              </div>
              
              {/* Timeline rows - scrollable both directions */}
              <div
                ref={timelineRowsScrollRef}
                id="timeline-rows-scroll"
                className={styles.timelineRowsScroll}
                onScroll={(e) => {
                  const machineLabels = document.getElementById('machine-labels-scroll')
                  if (machineLabels) {
                    machineLabels.scrollTop = e.currentTarget.scrollTop
                  }
                  // Sync horizontal scroll with header
                  const header = e.currentTarget.previousElementSibling as HTMLElement
                  if (header) {
                    header.scrollLeft = e.currentTarget.scrollLeft
                  }
                }}
              >
                <div className={styles.schedulingBoardTimeline} ref={timelineRef} style={{ 
                  width: timeline.totalWidth,
                  minHeight: filteredMachines.length * MACHINE_ROW_HEIGHT
                }}>
                  {/* Vertical grid lines for all rows */}
                  {timeline.getTimeMarks().map((mark) => (
                    <div
                      key={`full-grid-${mark.time}`}
                      className={`${styles.fullGridLine} ${mark.type === 'major' ? styles.fullGridLineMajor : styles.fullGridLineMinor}`}
                      style={{ left: mark.x }}
                    />
                  ))}
                  
                  {/* 下班時間遮罩 (Off-work hour overlays) */}
                  {getOffWorkOverlays.map((overlay, idx) => (
                    <div
                      key={`offwork-overlay-${idx}`}
                      className={styles.offWorkOverlay}
                      style={{
                        position: 'absolute',
                        left: timeline.timeToX(overlay.startHour),
                        width: timeline.durationToWidth(overlay.endHour - overlay.startHour),
                        top: 0,
                        height: '100%',
                        background: 'repeating-linear-gradient(45deg, rgba(180, 180, 180, 0.25), rgba(180, 180, 180, 0.25) 10px, rgba(160, 160, 160, 0.2) 10px, rgba(160, 160, 160, 0.2) 20px)',
                        pointerEvents: 'none',
                        zIndex: 1,
                        borderLeft: '2px solid rgba(200, 200, 200, 0.5)',
                        boxShadow: 'inset 0 0 20px rgba(0, 0, 0, 0.2)'
                      }}
                      title="下班時間"
                    />
                  ))}
                  
                  {filteredMachines.map((machine, index) => {
                    const y = index * MACHINE_ROW_HEIGHT
                    return (
                      <div
                        key={machine.machine_id}
                        className={styles.timelineRow}
                        style={{
                          top: y,
                          width: timeline.totalWidth
                        }}
                      >
                        {/* Row content container */}
                        <div className={styles.rowContent}>
                          {/* Downtime slots */}
                          {downtimeSlots
                            .filter(slot => slot.machineId === machine.machine_id)
                            .map(slot => (
                              <div
                                key={slot.id}
                                className={styles.downtimeSlot}
                                style={{
                                  left: timeline.timeToX(slot.startHour),
                                  width: timeline.durationToWidth(slot.endHour - slot.startHour)
                                }}
                              >
                                <span className={styles.downtimeIcon}>⏸</span>
                                <span className={styles.downtimeText}>停機</span>
                                <span className={styles.downtimeTime}>
                                  {formatTime(slot.startHour)} - {formatTime(slot.endHour)}
                                </span>
                              </div>
                            ))}
                          
                          {/* Work order cards */}
                          {filteredOrders
                            .filter(order => order.machineId === machine.machine_id)
                            .map(order => {
                              const isDragging = dragState?.order.id === order.id
                              // 如果正在拖動且有預覽位置，使用預覽位置；否則使用原位置
                              const displayMachine = isDragging && dragPreview ? dragPreview.machineId : order.machineId
                              const displayStart = isDragging && dragPreview ? dragPreview.startHour : order.startHour
                              const displayEnd = isDragging && dragPreview ? dragPreview.endHour : order.endHour
                              
                              // 如果卡片被拖到其他機台，在原機台不顯示
                              if (isDragging && dragPreview && dragPreview.machineId !== machine.machine_id) {
                                return null
                              }
                              
                              const left = timeline.timeToX(displayStart)
                              const width = timeline.durationToWidth(displayEnd - displayStart)
                              
                              return (
                                <div
                                  key={order.id}
                                  style={{
                                    position: 'absolute',
                                    left,
                                    width,
                                    top: 4,
                                    height: MACHINE_ROW_HEIGHT - 8,
                                    background: order.isModified 
                                      ? `linear-gradient(135deg, rgba(234,179,8,0.3), rgba(234,179,8,0.15))` 
                                      : `linear-gradient(135deg, ${getStatusColor(order.status)}22, ${getStatusColor(order.status)}11)`,
                                    borderRadius: 6,
                                    padding: '4px 8px',
                                    boxSizing: 'border-box',
                                    cursor: 'grab',
                                    transition: isDragging ? 'none' : 'all 0.2s ease',
                                    opacity: isDragging ? 0.7 : 1,
                                    zIndex: isDragging ? 1000 : 10,
                                    boxShadow: isDragging 
                                      ? (isOffWorkConflict 
                                          ? '0 8px 16px rgba(220, 38, 38, 0.6), 0 0 0 3px rgba(220, 38, 38, 0.3)' 
                                          : `0 8px 24px ${getStatusColor(order.status)}66`) 
                                      : (order.isModified 
                                          ? '0 2px 12px rgba(234,179,8,0.5)' 
                                          : `0 2px 8px ${getStatusColor(order.status)}33`),
                                    border: isDragging && isOffWorkConflict 
                                      ? '2px solid rgb(220, 38, 38)' 
                                      : (order.isModified 
                                          ? '2px solid #eab308' 
                                          : `2px solid ${getStatusColor(order.status)}`),
                                    display: 'flex',
                                    flexDirection: 'column',
                                    justifyContent: 'center',
                                    overflow: 'hidden'
                                  }}
                                  onMouseDown={(e) => handleCardMouseDown(e, order)}
                                >
                                  <div style={{ 
                                    fontSize: 17, 
                                    fontWeight: 700, 
                                    color: getStatusColor(order.status),
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 4
                                  }}>
                                    {order.productId}
                                    {order.isSplit && order.splitPart && order.totalSplits && (
                                      <span style={{
                                        fontSize: 12,
                                        padding: '1px 4px',
                                        background: 'rgba(234,179,8,0.2)',
                                        border: '1px solid rgba(234,179,8,0.4)',
                                        borderRadius: 3,
                                        color: '#eab308'
                                      }}>
                                        {`${order.splitPart}/${order.totalSplits}`}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          
                          {/* 顯示正在拖動到此機台的卡片預覽 */}
                          {dragState && dragPreview && dragPreview.machineId === machine.machine_id && 
                           dragState.order.machineId !== machine.machine_id && (
                            <div
                              style={{
                                position: 'absolute',
                                left: timeline.timeToX(dragPreview.startHour),
                                width: timeline.durationToWidth(dragPreview.endHour - dragPreview.startHour),
                                top: 4,
                                height: MACHINE_ROW_HEIGHT - 8,
                                background: `linear-gradient(135deg, ${getStatusColor(dragState.order.status)}22, ${getStatusColor(dragState.order.status)}11)`,
                                border: `2px solid ${getStatusColor(dragState.order.status)}`,
                                borderRadius: 6,
                                padding: '4px 8px',
                                boxSizing: 'border-box',
                                cursor: 'grabbing',
                                opacity: 0.7,
                                zIndex: 1000,
                                boxShadow: `0 8px 24px ${getStatusColor(dragState.order.status)}66`,
                                display: 'flex',
                                flexDirection: 'column',
                                justifyContent: 'center',
                                overflow: 'hidden',
                                pointerEvents: 'none'
                              }}
                            >
                              <div style={{ 
                                fontSize: 11, 
                                fontWeight: 700, 
                                color: getStatusColor(dragState.order.status),
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis'
                              }}>
                                {dragState.order.productId}
                              </div>
                              <div style={{ 
                                fontSize: 9, 
                                color: 'rgba(230,238,248,0.7)',
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis'
                              }}>
                                {dragState.order.orderId}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
            
            {/* Drag tooltip - inside boardContainer with absolute positioning */}
            {dragTooltip && (
              <div
                className="drag-tooltip"
                style={{
                  position: 'absolute',
                  left: dragTooltip.x + 15,
                  top: dragTooltip.y - 40,
                  background: 'rgba(15,23,36,0.95)',
                  border: '1px solid rgba(30,160,233,0.5)',
                  borderRadius: 8,
                  padding: '8px 12px',
                  fontSize: 12,
                  color: 'rgba(255,255,255,0.9)',
                  pointerEvents: 'none',
                  zIndex: 10000,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                  whiteSpace: 'nowrap'
                }}
              >
                <div>開始：{dragTooltip.start}</div>
                <div>結束：{dragTooltip.end}</div>
                <div>工時：{dragTooltip.duration}</div>
              </div>
            )}
          </div>
          {/* end of scheduling-main-wrapper */}
        </div>
        {/* end of scheduling-content */}
      </div>

      {/* Downtime form modal */}
      {showDowntimeForm && (
        <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(0,0,0,0.7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10001
            }}
            onClick={() => setShowDowntimeForm(false)}
          >
            <div
              style={{
                background: 'linear-gradient(135deg, rgba(15,23,36,0.98), rgba(7,16,35,0.95))',
                border: '1px solid rgba(239,68,68,0.3)',
                borderRadius: 12,
                padding: 24,
                width: 400,
                maxWidth: '90%',
                boxShadow: '0 8px 32px rgba(0,0,0,0.5)'
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h2 style={{ margin: 0, marginBottom: 20, color: '#ef4444' }}>新增停機時段</h2>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div>
                  <label style={{ display: 'block', marginBottom: 8, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    機台
                  </label>
                  <select
                    value={downtimeForm.machineId}
                    onChange={(e) => setDowntimeForm({ ...downtimeForm, machineId: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6,
                      color: '#fff',
                      fontSize: 14,
                      boxSizing: 'border-box'
                    }}
                  >
                    {filteredMachines.map(m => (
                      <option key={m.machine_id} value={m.machine_id} style={{ background: '#1a2332' }}>
                        {m.machine_id} ({m.area}區)
                      </option>
                    ))}
                  </select>
                </div>
                
                <div>
                  <label style={{ display: 'block', marginBottom: 8, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    開始時間
                  </label>
                  <input
                    type="time"
                    value={downtimeForm.startTime}
                    onChange={(e) => setDowntimeForm({ ...downtimeForm, startTime: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6,
                      color: '#fff',
                      fontSize: 14,
                      boxSizing: 'border-box'
                    }}
                  />
                </div>
                
                <div>
                  <label style={{ display: 'block', marginBottom: 8, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    結束時間
                  </label>
                  <input
                    type="time"
                    value={downtimeForm.endTime}
                    onChange={(e) => setDowntimeForm({ ...downtimeForm, endTime: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6,
                      color: '#fff',
                      fontSize: 14,
                      boxSizing: 'border-box'
                    }}
                  />
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
                <button
                  onClick={() => setShowDowntimeForm(false)}
                  style={{
                    flex: 1,
                    padding: '10px 16px',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    color: 'rgba(255,255,255,0.7)',
                    cursor: 'pointer',
                    fontSize: 14,
                    fontWeight: 600
                  }}
                >
                  取消
                </button>
                <button
                  onClick={handleAddDowntime}
                  style={{
                    flex: 1,
                    padding: '10px 16px',
                    background: 'linear-gradient(135deg, #ef4444, #dc2626)',
                    border: 'none',
                    borderRadius: 6,
                    color: '#fff',
                    cursor: 'pointer',
                    fontSize: 14,
                    fontWeight: 600
                  }}
                >
                  新增
                </button>
              </div>
            </div>
          </div>
      )}
        
      {/* AI Scheduling Config Modal */}
      {showSchedulingConfig && (
        <div
            style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(0,0,0,0.7)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 10002
            }}
            onClick={() => setShowSchedulingConfig(false)}
          >
            <div
              style={{
                background: 'linear-gradient(135deg, rgba(15,23,36,0.98), rgba(7,16,35,0.95))',
                border: '1px solid rgba(30,160,233,0.3)',
                borderRadius: 12,
                padding: 24,
                width: 420,
                maxWidth: '90%',
                boxShadow: '0 8px 32px rgba(0,0,0,0.5)'
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h2 style={{ margin: 0, marginBottom: 16, color: '#1ea0e9', fontSize: 20 }}>
                🤖 自動排程配置
              </h2>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                
                {/* 合併設定 */}
                <div>
                  <h3 style={{ margin: 0, marginBottom: 10, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    🔄 訂單合併設定
                  </h3>
                  
                  <label style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    padding: '10px 12px',
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    marginBottom: 8
                  }}>
                    <input
                      type="checkbox"
                      checked={schedulingConfig.merge_enabled}
                      onChange={(e) => setSchedulingConfig({
                        ...schedulingConfig,
                        merge_enabled: e.target.checked
                      })}
                      style={{ marginRight: 10 }}
                    />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>啟用相同品項合併</div>
                      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                        將相同品項的訂單合併生產，減少換模次數
                      </div>
                    </div>
                  </label>
                  
                  {schedulingConfig.merge_enabled && (
                    <div style={{ marginTop: 12, paddingLeft: 8 }}>
                      <div style={{ marginBottom: 8 }}>
                        <label style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)', display: 'block', marginBottom: 4 }}>
                          合併時間窗口（週）
                        </label>
                        <input
                          type="number"
                          min="1"
                          max="8"
                          value={schedulingConfig.merge_window_weeks}
                          onChange={(e) => setSchedulingConfig({
                            ...schedulingConfig,
                            merge_window_weeks: parseInt(e.target.value) || 2
                          })}
                          style={{
                            width: '100%',
                            padding: '6px 10px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: 4,
                            color: '#fff',
                            fontSize: 13
                          }}
                        />
                        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', marginTop: 2 }}>
                          在 {schedulingConfig.merge_window_weeks} 週內交期的相同品項可合併
                        </div>
                      </div>
                      
                      <div>
                        <label style={{ fontSize: 12, color: 'rgba(255,255,255,0.7)', display: 'block', marginBottom: 4 }}>
                          時間閾值（%）
                        </label>
                        <input
                          type="number"
                          min="0"
                          max="50"
                          value={schedulingConfig.time_threshold_pct}
                          onChange={(e) => setSchedulingConfig({
                            ...schedulingConfig,
                            time_threshold_pct: parseInt(e.target.value) || 10
                          })}
                          style={{
                            width: '100%',
                            padding: '6px 10px',
                            background: 'rgba(255,255,255,0.05)',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: 4,
                            color: '#fff',
                            fontSize: 13
                          }}
                        />
                        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', marginTop: 2 }}>
                          允許時間差異在 {schedulingConfig.time_threshold_pct}% 內視為可合併
                        </div>
                      </div>
                    </div>
                  )}
                </div>
                
                {/* 重新排程選項 */}
                <div>
                  <h3 style={{ margin: 0, marginBottom: 10, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    🔄 排程範圍
                  </h3>
                  
                  <label style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    padding: '10px 12px',
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    cursor: 'pointer'
                  }}>
                    <input
                      type="checkbox"
                      checked={schedulingConfig.reschedule_all}
                      onChange={(e) => setSchedulingConfig({
                        ...schedulingConfig,
                        reschedule_all: e.target.checked
                      })}
                      style={{ marginRight: 10 }}
                    />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>重新排程所有訂單</div>
                      <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                        包括已排程的訂單，清空現有排程重新計算（未勾選則只排程「未排程」狀態的訂單）
                      </div>
                    </div>
                  </label>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
                <button
                  onClick={() => setShowSchedulingConfig(false)}
                  style={{
                    flex: 1,
                    padding: '10px 14px',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    color: 'rgba(255,255,255,0.7)',
                    cursor: 'pointer',
                    fontSize: 13,
                    fontWeight: 600
                  }}
                >
                  取消
                </button>
                <button
                  onClick={handleScheduling}
                  disabled={isScheduling}
                  style={{
                    flex: 1,
                    padding: '10px 14px',
                    background: isScheduling 
                      ? 'rgba(128,128,128,0.5)'
                      : 'linear-gradient(135deg, #1ea0e9, #7c3aed)',
                    border: 'none',
                    borderRadius: 6,
                    color: '#fff',
                    cursor: isScheduling ? 'not-allowed' : 'pointer',
                    fontSize: 13,
                    fontWeight: 600,
                    boxShadow: isScheduling ? 'none' : '0 4px 12px rgba(30,160,233,0.3)',
                    opacity: isScheduling ? 0.6 : 1
                  }}
                >
                  {isScheduling ? '⏳ 排程中...' : '🚀 開始排程'}
                </button>
              </div>
            </div>
          </div>
        )}
        
        {/* Cross-day scheduling confirmation dialog (跨日排程確認對話框) */}
        {showCrossDayDialog && pendingCrossDaySchedule && (
          <div style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10000
          }}>
            <div style={{
              background: 'linear-gradient(135deg, rgba(15, 23, 36, 0.98), rgba(20, 30, 48, 0.98))',
              border: '1px solid rgba(234,179,8,0.3)',
              borderRadius: 12,
              padding: 24,
              maxWidth: 480,
              width: '90%',
              boxShadow: '0 20px 60px rgba(0,0,0,0.5)'
            }}>
              <div style={{ 
                fontSize: 18, 
                fontWeight: 700, 
                color: '#eab308',
                marginBottom: 16,
                display: 'flex',
                alignItems: 'center',
                gap: 10
              }}>
                ⚠️ 跨日排程確認
              </div>
              
              <div style={{ 
                fontSize: 14, 
                color: 'rgba(255,255,255,0.9)', 
                lineHeight: 1.6,
                marginBottom: 20
              }}>
                此工單排程時間與下班時間重疊，是否進行跨日排程？
                <div style={{
                  marginTop: 12,
                  padding: 12,
                  background: 'rgba(234,179,8,0.1)',
                  borderRadius: 6,
                  fontSize: 13
                }}>
                  <div><strong>子件編號：</strong>{pendingCrossDaySchedule.order.productId}</div>
                  <div style={{ marginTop: 4 }}>
                    <strong>排程時間：</strong>
                    {formatTime(pendingCrossDaySchedule.newStartHour)} - {formatTime(pendingCrossDaySchedule.newEndHour)}
                  </div>
                </div>
              </div>
              
              <div style={{ 
                fontSize: 12, 
                color: 'rgba(255,255,255,0.6)',
                marginBottom: 20,
                lineHeight: 1.5
              }}>
                選擇「是」將會把訂單分割成兩部分，分別在不同日期的工作時間內執行。<br/>
                選擇「否」將取消此次排程調整。
              </div>
              
              <div style={{ display: 'flex', gap: 10 }}>
                <button
                  onClick={() => {
                    // Cancel: revert to original position (取消：回到原位置)
                    setShowCrossDayDialog(false)
                    setPendingCrossDaySchedule(null)
                  }}
                  style={{
                    flex: 1,
                    padding: '12px 16px',
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: 6,
                    color: 'rgba(255,255,255,0.7)',
                    cursor: 'pointer',
                    fontSize: 14,
                    fontWeight: 600
                  }}
                >
                  否，取消排程
                </button>
                <button
                  onClick={() => {
                    // Confirm: proceed with cross-day scheduling (確認：執行跨日排程)
                    if (!pendingCrossDaySchedule) return
                    
                    const { order, newStartHour, newEndHour, targetMachine } = pendingCrossDaySchedule
                    
                    // Find the off-work period that overlaps with this schedule
                    // (找出與此排程重疊的下班時間區間)
                    const overlappingOffWork = getOffWorkOverlays.find(overlay => 
                      newStartHour < overlay.endHour && newEndHour > overlay.startHour
                    )
                    
                    if (!overlappingOffWork) {
                      // No overlap found, just update normally
                      setWorkOrders(prev => prev.map(wo =>
                        wo.id === order.id
                          ? { ...wo, machineId: targetMachine, startHour: newStartHour, endHour: newEndHour, isModified: true }
                          : wo
                      ))
                      setShowCrossDayDialog(false)
                      setPendingCrossDaySchedule(null)
                      return
                    }
                    
                    // Split the order at the off-work boundary (在下班時間邊界分割訂單)
                    const offWorkStart = overlappingOffWork.startHour
                    const offWorkEnd = overlappingOffWork.endHour
                    
                    // Calculate the two parts (計算兩個部分)
                    // Part 1: Before off-work (第一部分：下班前)
                    const part1Start = newStartHour
                    const part1End = Math.min(newEndHour, offWorkStart)
                    
                    // Part 2: After off-work (第二部分：下班後)
                    const part2Start = Math.max(newStartHour, offWorkEnd)
                    const part2End = newEndHour
                    
                    // Generate unique IDs for the split orders (為分割的訂單生成唯一ID)
                    const baseSplitId = `split-${Date.now()}`
                    const part1Id = `${baseSplitId}-1`
                    const part2Id = `${baseSplitId}-2`
                    
                    // Create the two split orders (創建兩個分割的訂單)
                    const newOrders: WorkOrder[] = []
                    
                    if (part1End > part1Start) {
                      // Part 1 exists (第一部分存在)
                      newOrders.push({
                        ...order,
                        id: part1Id,
                        machineId: targetMachine,
                        startHour: part1Start,
                        endHour: part1End,
                        linkedOrderId: part2Id, // Link to part 2 (連結到第二部分)
                        isSplit: true,
                        splitPart: 1,
                        isModified: true,
                        originalId: order.originalId || order.id // 繼承原始 ID
                      })
                    }
                    
                    if (part2End > part2Start) {
                      // Part 2 exists (第二部分存在)
                      newOrders.push({
                        ...order,
                        id: part2Id,
                        machineId: targetMachine,
                        startHour: part2Start,
                        endHour: part2End,
                        linkedOrderId: part1Id, // Link to part 1 (連結到第一部分)
                        isSplit: true,
                        splitPart: 2,
                        isModified: true,
                        originalId: order.originalId || order.id // 繼承原始 ID
                      })
                    }
                    
                    // Remove the original order and add the split orders
                    // (移除原訂單並添加分割後的訂單)
                    setWorkOrders(prev => [
                      ...prev.filter(wo => wo.id !== order.id),
                      ...newOrders
                    ])
                    
                    setShowCrossDayDialog(false)
                    setPendingCrossDaySchedule(null)
                  }}
                  style={{
                    flex: 1,
                    padding: '12px 16px',
                    background: 'linear-gradient(135deg, #eab308, #d97706)',
                    border: 'none',
                    borderRadius: 6,
                    color: '#fff',
                    cursor: 'pointer',
                    fontSize: 14,
                    fontWeight: 600,
                    boxShadow: '0 4px 12px rgba(234,179,8,0.3)'
                  }}
                >
                  是，進行跨日排程
                </button>
              </div>
            </div>
          </div>
        )}
    </div>
  )
}
