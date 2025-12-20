import React, { useState, useRef, useEffect, useMemo } from 'react'
import { useTimeline } from '../hooks/useTimeline'
import { api } from '../api/api'
import { Order } from '../types'
import { 
  executeAutoScheduling, 
  SchedulingStrategy, 
  MergeStrategy,
  SchedulingConfig 
} from '../utils/schedulingAlgorithms'
import styles from './Scheduling.module.css'

type WorkOrder = {
  id: string
  orderId: string
  productId: string
  machineId: string
  startHour: number
  endHour: number
  status: 'running' | 'idle'
  aiLocked: boolean
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

export default function SchedulingPage() {
  const timeline = useTimeline()
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0])
  const [viewMode, setViewMode] = useState<ViewMode>('machine')
  const [filteredStatus, setFilteredStatus] = useState<'all' | 'running' | 'idle'>('all')
  const [orders, setOrders] = useState<Order[]>([])
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [snapLineX, setSnapLineX] = useState<number | null>(null)
  const [dragTooltip, setDragTooltip] = useState<{ x: number; y: number; start: string; end: string; duration: string } | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  
  // 機台和區域狀態
  const [machines, setMachines] = useState<{ machine_id: string; area: string }[]>([])
  const [areas, setAreas] = useState<string[]>([])
  const [selectedArea, setSelectedArea] = useState<string>('all')
  
  const MACHINE_ROW_HEIGHT = 60
  const MACHINE_LABEL_WIDTH = 120
  
  // Downtime slots state
  const [downtimeSlots, setDowntimeSlots] = useState<DowntimeSlot[]>([])
  
  // Downtime form state
  const [showDowntimeForm, setShowDowntimeForm] = useState(false)
  const [downtimeForm, setDowntimeForm] = useState({
    machineId: 'A01',
    startTime: '08:00',
    endTime: '09:00'
  })
  
  // AI Scheduling config state
  const [showSchedulingConfig, setShowSchedulingConfig] = useState(false)
  const [schedulingStrategy, setSchedulingStrategy] = useState<SchedulingStrategy>('quality-first')
  const [mergeStrategy, setMergeStrategy] = useState<MergeStrategy>('merge-with-deadline')
  
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
        setDowntimeSlots([])
      }
    }
    loadDowntimes()
  }, [selectedDate])
  
  // Filter machines by selected area
  const filteredMachines = selectedArea === 'all' 
    ? machines 
    : machines.filter(m => m.area === selectedArea)
  
  // Manual work orders state (for drag-and-drop modifications)
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  
  // Helper: Convert HH:MM string to decimal hours
  const timeStringToHours = (timeStr: string): number => {
    const [hours, minutes] = timeStr.split(':').map(Number)
    return hours + minutes / 60
  }
  
  // Convert Orders to WorkOrders with smart scheduling (only when orders change)
  useEffect(() => {
    const newWorkOrders = orders.map((order, index) => {
      const woId = `wo-${order.id}`
      
      // Estimate duration based on quantity (1 unit = 0.01 hour)
      const estimatedDuration = Math.max(1, Math.min(6, order.quantity * 0.01))
      
      // If this work order already exists, check if we should update from order data
      const existing = workOrders.find(wo => wo.id === woId)
      if (existing) {
        // If order has scheduled time, use it (order page updated)
        if (order.scheduled_start_time && order.scheduled_end_time) {
          const startHour = timeStringToHours(order.scheduled_start_time)
          const endHour = timeStringToHours(order.scheduled_end_time)
          
          return {
            ...existing,
            orderId: order.order_number,
            productId: order.product_code,
            startHour,
            endHour,
            status: (order.priority === 1 ? 'running' : 'idle') as 'running' | 'idle',
            aiLocked: order.status === 'SCHEDULED'
          }
        }
        
        // Otherwise just update duration and info, keep position
        const newEndHour = existing.startHour + estimatedDuration
        return {
          ...existing,
          orderId: order.order_number,
          productId: order.product_code,
          endHour: newEndHour,
          status: (order.priority === 1 ? 'running' : 'idle') as 'running' | 'idle',
          aiLocked: order.status === 'SCHEDULED'
        }
      }
      
      // New work order - check if order has scheduled time
      let startHour: number
      let endHour: number
      let machineId: string
      
      if (order.scheduled_start_time && order.scheduled_end_time) {
        // Use time from order
        startHour = timeStringToHours(order.scheduled_start_time)
        endHour = timeStringToHours(order.scheduled_end_time)
        machineId = machines.length > 0 ? machines[index % machines.length].machine_id : 'A01'
      } else {
        // Auto-assign time
        machineId = machines.length > 0 ? machines[index % machines.length].machine_id : 'A01'
        const timeSlotWidth = (timeline.t1 - timeline.t0) / Math.max(orders.length, 1)
        const baseStartHour = timeline.t0 + (index * timeSlotWidth)
        const hash = order.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
        const consistentOffset = ((hash % 100) / 100 - 0.5) * 0.5
        startHour = Math.max(timeline.t0, Math.min(timeline.t1 - estimatedDuration, baseStartHour + consistentOffset))
        endHour = startHour + estimatedDuration
      }
      
      const status: 'running' | 'idle' = order.priority === 1 ? 'running' : 'idle'
      const aiLocked = order.status === 'SCHEDULED'
      
      return {
        id: woId,
        orderId: order.order_number,
        productId: order.product_code,
        machineId,
        startHour,
        endHour,
        status,
        aiLocked
      }
    })
    
    setWorkOrders(newWorkOrders)
  }, [orders, timeline.t0, timeline.t1])
  
  // Helper: Convert decimal hours to HH:MM string
  const hoursToTimeString = (hours: number): string => {
    const h = Math.floor(hours)
    const m = Math.round((hours - h) * 60)
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  }
  
  // Save schedules and sync back to orders whenever workOrders change
  useEffect(() => {
    if (workOrders.length === 0 || orders.length === 0) return
    
    // Update orders with schedule info
    const updateOrders = async () => {
      for (const wo of workOrders) {
        // Find corresponding order
        const order = orders.find(o => o.order_number === wo.orderId)
        if (!order) continue
        
        // Convert times to HH:MM format
        const startTime = hoursToTimeString(wo.startHour)
        const endTime = hoursToTimeString(wo.endHour)
        
        // Check if schedule changed
        if (order.scheduled_start_time !== startTime || order.scheduled_end_time !== endTime) {
          // Update order with new schedule
          await api.updateOrder(order.id, {
            ...order,
            scheduled_date: selectedDate,
            scheduled_start_time: startTime,
            scheduled_end_time: endTime
          })
        }
      }
    }
    
    updateOrders()
    
    // Also save to localStorage for legacy support
    const scheduleData = workOrders.map(wo => ({
      orderId: wo.orderId,
      machineId: wo.machineId,
      startHour: wo.startHour,
      endHour: wo.endHour
    }))
    localStorage.setItem('eps_schedules', JSON.stringify(scheduleData))
  }, [workOrders, selectedDate])
  
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
    
    // Filter by selected date - 如果訂單沒有 scheduled_date 或 scheduled_date 等於當前選擇的日期，就顯示
    const order = orders.find(o => o.order_number === wo.orderId)
    if (order && order.scheduled_date) {
      // 如果訂單已經有排程日期，則只顯示與選擇日期相符的訂單
      if (order.scheduled_date !== selectedDate) {
        return false
      }
    }
    // 如果訂單沒有 scheduled_date，則顯示在當前選擇的日期（讓用戶可以排程）
    
    return true
  })
  
  // Format time for display
  const formatTime = (hour: number): string => {
    const h = Math.floor(hour)
    const m = Math.round((hour - h) * 60)
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
    const mouseX = e.clientX - rect.left - MACHINE_LABEL_WIDTH
    
    setDragState({
      order,
      offsetX: mouseX - timeline.timeToX(order.startHour),
      initialX: mouseX
    })
  }
  
  // Handle mouse move during drag
  useEffect(() => {
    if (!dragState) return
    
    const handleMouseMove = (e: MouseEvent) => {
      if (!timelineRef.current) return
      
      const rect = timelineRef.current.getBoundingClientRect()
      const mouseX = e.clientX - rect.left - MACHINE_LABEL_WIDTH
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
      setSnapLineX(snappedX + MACHINE_LABEL_WIDTH)
      
      // Update tooltip with snapped values
      setDragTooltip({
        x: e.clientX,
        y: e.clientY,
        start: formatTime(clampedStart),
        end: formatTime(clampedEnd),
        duration: formatDuration(duration)
      })
    }
    
    const handleMouseUp = (e: MouseEvent) => {
      if (!timelineRef.current || !dragState) return
      
      const rect = timelineRef.current.getBoundingClientRect()
      const mouseX = e.clientX - rect.left - MACHINE_LABEL_WIDTH
      const mouseY = e.clientY - rect.top
      
      // Calculate new start time with snapping
      const rawStartTime = timeline.xToTime(mouseX - dragState.offsetX)
      const snappedStart = timeline.snapToGrid(rawStartTime)
      const duration = dragState.order.endHour - dragState.order.startHour
      
      // Clamp to valid range
      const clampedStart = Math.max(timeline.t0, Math.min(timeline.t1 - duration, snappedStart))
      const clampedEnd = clampedStart + duration
      
      // Determine target machine
      const machineIndex = Math.floor(mouseY / MACHINE_ROW_HEIGHT)
      const targetMachine = filteredMachines[machineIndex]?.machine_id || dragState.order.machineId
      
      // Check for downtime conflicts
      const hasDowntimeConflict = downtimeSlots.some(slot =>
        slot.machineId === targetMachine &&
        slot.startHour < clampedEnd &&
        slot.endHour > clampedStart
      )
      
      // Check for work order conflicts
      const hasOrderConflict = workOrders.some(wo =>
        wo.id !== dragState.order.id &&
        wo.machineId === targetMachine &&
        wo.startHour < clampedEnd &&
        wo.endHour > clampedStart
      )
      
      if (!hasDowntimeConflict && !hasOrderConflict) {
        // Update order with precise time
        setWorkOrders(prev => prev.map(wo =>
          wo.id === dragState.order.id
            ? { ...wo, machineId: targetMachine, startHour: clampedStart, endHour: clampedEnd }
            : wo
        ))
      }
      
      // Clear drag state
      setDragState(null)
      setSnapLineX(null)
      setDragTooltip(null)
    }
    
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragState, timeline, machines, downtimeSlots])
  
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
        machineId: machines.length > 0 ? machines[0].machine_id : 'A01',
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
  
  // Handle AI Auto Scheduling
  const handleAutoScheduling = async () => {
    const config: SchedulingConfig = {
      strategy: schedulingStrategy,
      mergeStrategy: mergeStrategy,
      availableMachines: filteredMachines.map(m => parseInt(m.machine_id.replace(/[^0-9]/g, '')) || 1),
      workHoursPerDay: 8,
      startHour: timeline.t0,
      endHour: timeline.t1
    }
    
    // 從後端獲取機台產品歷史數據
    const machineHistory = await api.getMachineHistory()
    
    // 執行 AI 排程
    const results = executeAutoScheduling(
      orders,
      config,
      machineHistory,
      downtimeSlots
    )
    
    // 將排程結果轉換為 WorkOrders
    const newWorkOrders = results.map(result => {
      const order = orders.find(o => o.order_number === result.orderId)
      if (!order) return null
      
      return {
        id: `wo-${order.id}`,
        orderId: result.orderId,
        productId: order.product_code,
        machineId: result.machineId,
        startHour: result.startHour,
        endHour: result.endHour,
        status: (order.priority === 1 ? 'running' : 'idle') as 'running' | 'idle',
        aiLocked: true // AI 排程的訂單會鎖定
      }
    }).filter(wo => wo !== null) as WorkOrder[]
    
    setWorkOrders(newWorkOrders)
    setShowSchedulingConfig(false)
    
    // 顯示排程完成通知
    alert(`AI 排程完成！\n已安排 ${results.length} 個訂單\n策略: ${getStrategyLabel(schedulingStrategy)}\n合併策略: ${getMergeStrategyLabel(mergeStrategy)}`)
  }
  
  const getStrategyLabel = (strategy: SchedulingStrategy): string => {
    const labels = {
      'quality-first': '品質優先',
      'time-first': '時間優先',
      'frequency-first': '頻率優先'
    }
    return labels[strategy]
  }
  
  const getMergeStrategyLabel = (strategy: MergeStrategy): string => {
    const labels = {
      'merge-all': '合併所有相同品項',
      'merge-with-deadline': '交期內合併相同品項'
    }
    return labels[strategy]
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
          >
            AI 重新排程
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
                onWheel={(e) => {
                  if (e.shiftKey) {
                    e.preventDefault()
                    const container = e.currentTarget
                    container.scrollLeft += e.deltaY
                    // Sync with header
                    const header = container.previousElementSibling as HTMLElement
                    if (header) {
                      header.scrollLeft = container.scrollLeft
                    }
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
                              const left = timeline.timeToX(order.startHour)
                              const width = timeline.durationToWidth(order.endHour - order.startHour)
                              
                              return (
                                <div
                                  key={order.id}
                                  style={{
                                    position: 'absolute',
                                    left,
                                    width,
                                    top: 4,
                                    height: MACHINE_ROW_HEIGHT - 8,
                                    background: `linear-gradient(135deg, ${getStatusColor(order.status)}22, ${getStatusColor(order.status)}11)`,
                                    border: `2px solid ${getStatusColor(order.status)}`,
                                    borderRadius: 6,
                                    padding: '4px 8px',
                                    boxSizing: 'border-box',
                                    cursor: 'grab',
                                    transition: isDragging ? 'none' : 'all 0.2s ease',
                                    opacity: isDragging ? 0.7 : 1,
                                    zIndex: isDragging ? 1000 : 10,
                                    boxShadow: isDragging 
                                      ? `0 8px 24px ${getStatusColor(order.status)}66` 
                                      : `0 2px 8px ${getStatusColor(order.status)}33`,
                                    display: 'flex',
                                    flexDirection: 'column',
                                    justifyContent: 'center',
                                    overflow: 'hidden'
                                  }}
                                  onMouseDown={(e) => handleCardMouseDown(e, order)}
                                >
                                  <div style={{ 
                                    fontSize: 11, 
                                    fontWeight: 700, 
                                    color: getStatusColor(order.status),
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis'
                                  }}>
                                    {order.orderId}
                                  </div>
                                  <div style={{ 
                                    fontSize: 9, 
                                    color: 'rgba(230,238,248,0.7)',
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis'
                                  }}>
                                    {order.productId}
                                  </div>
                                </div>
                              )
                            })}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
          {/* end of scheduling-main-wrapper */}
        </div>
        {/* end of scheduling-content */}
      </div>

      {/* Drag tooltip */}
      {dragTooltip && (
        <div
          className="drag-tooltip"
          style={{
            position: 'fixed',
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
                      fontSize: 14
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
                      fontSize: 14
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
                      fontSize: 14
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
                🤖 AI 自動排程配置
              </h2>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                {/* 機台選擇策略 */}
                <div>
                  <h3 style={{ margin: 0, marginBottom: 10, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    📊 機台選擇策略
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <label style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      padding: '10px 12px',
                      background: schedulingStrategy === 'quality-first' ? 'rgba(30,160,233,0.15)' : 'rgba(255,255,255,0.03)',
                      border: `2px solid ${schedulingStrategy === 'quality-first' ? '#1ea0e9' : 'rgba(255,255,255,0.1)'}`,
                      borderRadius: 6,
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}>
                      <input
                        type="radio"
                        name="strategy"
                        value="quality-first"
                        checked={schedulingStrategy === 'quality-first'}
                        onChange={(e) => setSchedulingStrategy(e.target.value as SchedulingStrategy)}
                        style={{ marginRight: 10 }}
                      />
                      <div>
                        <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>品質優先</div>
                        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                          選擇該模具良率最佳的機台
                        </div>
                      </div>
                    </label>
                    
                    <label style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      padding: '10px 12px',
                      background: schedulingStrategy === 'time-first' ? 'rgba(30,160,233,0.15)' : 'rgba(255,255,255,0.03)',
                      border: `2px solid ${schedulingStrategy === 'time-first' ? '#1ea0e9' : 'rgba(255,255,255,0.1)'}`,
                      borderRadius: 6,
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}>
                      <input
                        type="radio"
                        name="strategy"
                        value="time-first"
                        checked={schedulingStrategy === 'time-first'}
                        onChange={(e) => setSchedulingStrategy(e.target.value as SchedulingStrategy)}
                        style={{ marginRight: 10 }}
                      />
                      <div>
                        <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>時間優先</div>
                        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                          選擇生產時間最短的機台
                        </div>
                      </div>
                    </label>
                    
                    <label style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      padding: '10px 12px',
                      background: schedulingStrategy === 'frequency-first' ? 'rgba(30,160,233,0.15)' : 'rgba(255,255,255,0.03)',
                      border: `2px solid ${schedulingStrategy === 'frequency-first' ? '#1ea0e9' : 'rgba(255,255,255,0.1)'}`,
                      borderRadius: 6,
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}>
                      <input
                        type="radio"
                        name="strategy"
                        value="frequency-first"
                        checked={schedulingStrategy === 'frequency-first'}
                        onChange={(e) => setSchedulingStrategy(e.target.value as SchedulingStrategy)}
                        style={{ marginRight: 10 }}
                      />
                      <div>
                        <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>頻率優先</div>
                        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                          選擇該模具最常使用的機台
                        </div>
                      </div>
                    </label>
                  </div>
                </div>
                
                {/* 訂單合併策略 */}
                <div>
                  <h3 style={{ margin: 0, marginBottom: 10, fontSize: 14, color: 'rgba(255,255,255,0.9)' }}>
                    🔄 訂單合併策略
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <label style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      padding: '10px 12px',
                      background: mergeStrategy === 'merge-all' ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.03)',
                      border: `2px solid ${mergeStrategy === 'merge-all' ? '#22c55e' : 'rgba(255,255,255,0.1)'}`,
                      borderRadius: 6,
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}>
                      <input
                        type="radio"
                        name="merge"
                        value="merge-all"
                        checked={mergeStrategy === 'merge-all'}
                        onChange={(e) => setMergeStrategy(e.target.value as MergeStrategy)}
                        style={{ marginRight: 10 }}
                      />
                      <div>
                        <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>合併所有相同品項</div>
                        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                          不考慮交期問題，將相同品項全部合併
                        </div>
                      </div>
                    </label>
                    
                    <label style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      padding: '10px 12px',
                      background: mergeStrategy === 'merge-with-deadline' ? 'rgba(34,197,94,0.15)' : 'rgba(255,255,255,0.03)',
                      border: `2px solid ${mergeStrategy === 'merge-with-deadline' ? '#22c55e' : 'rgba(255,255,255,0.1)'}`,
                      borderRadius: 6,
                      cursor: 'pointer',
                      transition: 'all 0.2s'
                    }}>
                      <input
                        type="radio"
                        name="merge"
                        value="merge-with-deadline"
                        checked={mergeStrategy === 'merge-with-deadline'}
                        onChange={(e) => setMergeStrategy(e.target.value as MergeStrategy)}
                        style={{ marginRight: 10 }}
                      />
                      <div>
                        <div style={{ fontWeight: 600, color: '#fff', fontSize: 13 }}>交期內合併相同品項</div>
                        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', marginTop: 2 }}>
                          在所有交期都可達成的情況下合併
                        </div>
                      </div>
                    </label>
                  </div>
                </div>
                
                {/* 說明提示 */}
                <div style={{
                  padding: 12,
                  background: 'rgba(234,179,8,0.1)',
                  border: '1px solid rgba(234,179,8,0.3)',
                  borderRadius: 6
                }}>
                  <div style={{ fontSize: 12, color: '#eab308', fontWeight: 600, marginBottom: 6 }}>
                    💡 排程說明
                  </div>
                  <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: 'rgba(255,255,255,0.7)', lineHeight: 1.5 }}>
                    <li>AI 會根據歷史數據自動選擇最佳機台</li>
                    <li>急單會優先排程</li>
                    <li>自動避開停機時段</li>
                    <li>AI 排程的訂單會被鎖定 🔒</li>
                  </ul>
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
                  onClick={handleAutoScheduling}
                  style={{
                    flex: 1,
                    padding: '10px 14px',
                    background: 'linear-gradient(135deg, #1ea0e9, #7c3aed)',
                    border: 'none',
                    borderRadius: 6,
                    color: '#fff',
                    cursor: 'pointer',
                    fontSize: 13,
                    fontWeight: 600,
                    boxShadow: '0 4px 12px rgba(30,160,233,0.3)'
                  }}
                >
                  🚀 開始 AI 排程
                </button>
              </div>
            </div>
          </div>
        )}
    </div>
  )
}
