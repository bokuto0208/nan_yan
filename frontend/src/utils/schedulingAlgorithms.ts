import { Order } from '../types'

// 機台-模具歷史數據類型
export interface MachineProductHistory {
  machineId: number
  productCode: string
  totalProduced: number
  averageYieldRate: number // 良率 (0-1)
  averageProductionTime: number // 平均生產時間 (小時)
  productionCount: number // 生產次數
}

// 排程策略選項
export type SchedulingStrategy = 
  | 'quality-first'      // 品質優先：選擇良率最佳的機台
  | 'time-first'         // 時間優先：選擇生產時間最短的機台
  | 'frequency-first'    // 頻率優先：選擇最常使用的機台

// 訂單合併策略選項
export type MergeStrategy =
  | 'merge-all'          // 合併所有相同品項，不考慮交期
  | 'merge-with-deadline' // 在交期允許的情況下合併

// 排程配置
export interface SchedulingConfig {
  strategy: SchedulingStrategy
  mergeStrategy: MergeStrategy
  availableMachines: number[]
  workHoursPerDay: number // 每天工作時數
  startHour: number // 開始時間 (0-23)
  endHour: number // 結束時間 (0-24)
}

// 排程結果
export interface SchedulingResult {
  machineId: number
  startHour: number
  endHour: number
  orderId: string
  reason: string // 排程理由說明
}

/**
 * 根據策略選擇最佳機台
 */
export function selectBestMachine(
  productCode: string,
  strategy: SchedulingStrategy,
  history: MachineProductHistory[],
  availableMachines: number[]
): { machineId: number; reason: string } {
  // 過濾出該產品在各機台的歷史數據
  const productHistory = history.filter(h => 
    h.productCode === productCode && 
    availableMachines.includes(h.machineId)
  )
  
  if (productHistory.length === 0) {
    // 沒有歷史數據，隨機分配
    const machineId = availableMachines[0] || 1
    return {
      machineId,
      reason: '無歷史數據，使用預設機台'
    }
  }
  
  let selectedMachine: MachineProductHistory
  let reason: string
  
  switch (strategy) {
    case 'quality-first':
      // 選擇良率最高的機台
      selectedMachine = productHistory.reduce((best, current) => 
        current.averageYieldRate > best.averageYieldRate ? current : best
      )
      reason = `品質優先：機台 ${selectedMachine.machineId} 良率最佳 (${(selectedMachine.averageYieldRate * 100).toFixed(1)}%)`
      break
      
    case 'time-first':
      // 選擇生產時間最短的機台
      selectedMachine = productHistory.reduce((best, current) => 
        current.averageProductionTime < best.averageProductionTime ? current : best
      )
      reason = `時間優先：機台 ${selectedMachine.machineId} 生產時間最短 (${selectedMachine.averageProductionTime.toFixed(1)}h)`
      break
      
    case 'frequency-first':
      // 選擇生產次數最多的機台
      selectedMachine = productHistory.reduce((best, current) => 
        current.productionCount > best.productionCount ? current : best
      )
      reason = `頻率優先：機台 ${selectedMachine.machineId} 最常使用 (${selectedMachine.productionCount}次)`
      break
      
    default:
      selectedMachine = productHistory[0]
      reason = '使用預設策略'
  }
  
  return {
    machineId: selectedMachine.machineId,
    reason
  }
}

/**
 * 合併相同品項的訂單
 */
export function mergeOrders(
  orders: Order[],
  mergeStrategy: MergeStrategy
): Order[] {
  if (mergeStrategy === 'merge-all') {
    // 策略1: 合併所有相同品項，不考慮交期
    return mergeAllSameProducts(orders)
  } else {
    // 策略2: 在交期允許的情況下合併
    return mergeWithDeadlineConstraint(orders)
  }
}

/**
 * 合併所有相同品項的訂單（不考慮交期）
 */
function mergeAllSameProducts(orders: Order[]): Order[] {
  const productGroups = new Map<string, Order[]>()
  
  // 按產品代碼分組
  orders.forEach(order => {
    const existing = productGroups.get(order.product_code) || []
    existing.push(order)
    productGroups.set(order.product_code, existing)
  })
  
  const mergedOrders: Order[] = []
  
  productGroups.forEach((group, productCode) => {
    if (group.length === 1) {
      // 只有一個訂單，不需要合併
      mergedOrders.push(group[0])
    } else {
      // 合併多個訂單
      const totalQuantity = group.reduce((sum, o) => sum + o.quantity, 0)
      const earliestDueDate = group.reduce((earliest, o) => 
        o.due_date < earliest ? o.due_date : earliest
      , group[0].due_date)
      
      const mergedOrder: Order = {
        ...group[0],
        id: `merged-${Date.now()}-${productCode}`,
        order_number: `MRG-${group.map(o => o.order_number).join('+')}`,
        quantity: totalQuantity,
        due_date: earliestDueDate,
        customer_name: group.length > 1 ? `合併訂單 (${group.length}筆)` : group[0].customer_name
      }
      
      mergedOrders.push(mergedOrder)
    }
  })
  
  return mergedOrders
}

/**
 * 在交期允許的情況下合併相同品項
 */
function mergeWithDeadlineConstraint(orders: Order[]): Order[] {
  const productGroups = new Map<string, Order[]>()
  
  // 按產品代碼分組
  orders.forEach(order => {
    const existing = productGroups.get(order.product_code) || []
    existing.push(order)
    productGroups.set(order.product_code, existing)
  })
  
  const mergedOrders: Order[] = []
  
  productGroups.forEach((group, productCode) => {
    if (group.length === 1) {
      mergedOrders.push(group[0])
      return
    }
    
    // 按交期排序
    const sortedGroup = [...group].sort((a, b) => 
      new Date(a.due_date).getTime() - new Date(b.due_date).getTime()
    )
    
    const clusters: Order[][] = []
    let currentCluster: Order[] = [sortedGroup[0]]
    
    for (let i = 1; i < sortedGroup.length; i++) {
      const current = sortedGroup[i]
      const clusterTotal = currentCluster.reduce((sum, o) => sum + o.quantity, 0)
      const estimatedHours = Math.max(1, Math.min(6, clusterTotal * 0.01))
      
      // 計算如果加入當前訂單，能否在最早交期前完成
      const earliestDueDate = new Date(currentCluster[0].due_date)
      const currentDueDate = new Date(current.due_date)
      const daysDiff = (currentDueDate.getTime() - earliestDueDate.getTime()) / (1000 * 60 * 60 * 24)
      
      const newTotal = clusterTotal + current.quantity
      const newEstimatedHours = Math.max(1, Math.min(6, newTotal * 0.01))
      
      // 如果新的預估時間仍在交期內，則可以合併
      if (newEstimatedHours <= daysDiff * 8) { // 假設每天8小時工作
        currentCluster.push(current)
      } else {
        // 無法合併，開始新的集群
        clusters.push(currentCluster)
        currentCluster = [current]
      }
    }
    clusters.push(currentCluster)
    
    // 為每個集群創建合併訂單
    clusters.forEach(cluster => {
      if (cluster.length === 1) {
        mergedOrders.push(cluster[0])
      } else {
        const totalQuantity = cluster.reduce((sum, o) => sum + o.quantity, 0)
        const earliestDueDate = cluster[0].due_date
        
        const mergedOrder: Order = {
          ...cluster[0],
          id: `merged-${Date.now()}-${productCode}-${Math.random()}`,
          order_number: `MRG-${cluster.map(o => o.order_number).join('+')}`,
          quantity: totalQuantity,
          due_date: earliestDueDate,
          customer_name: `合併訂單 (${cluster.length}筆)`
        }
        
        mergedOrders.push(mergedOrder)
      }
    })
  })
  
  return mergedOrders
}

/**
 * 計算訂單的預估生產時間（小時）
 */
export function estimateProductionTime(
  quantity: number,
  productCode: string,
  history: MachineProductHistory[],
  machineId?: number
): number {
  // 如果有歷史數據，使用實際平均時間
  if (machineId) {
    const machineHistory = history.find(h => 
      h.productCode === productCode && h.machineId === machineId
    )
    if (machineHistory) {
      return machineHistory.averageProductionTime
    }
  }
  
  // 否則使用預設計算: 1 unit = 0.01 hour，範圍 1-6 小時
  return Math.max(1, Math.min(6, quantity * 0.01))
}

/**
 * 檢查機台在指定時段是否可用
 */
export function isMachineAvailable(
  machineId: number,
  startHour: number,
  endHour: number,
  existingSchedules: SchedulingResult[],
  downtimeSlots: { machineId: number; startHour: number; endHour: number }[]
): boolean {
  // 檢查是否與現有排程衝突
  const hasScheduleConflict = existingSchedules.some(schedule =>
    schedule.machineId === machineId &&
    schedule.startHour < endHour &&
    schedule.endHour > startHour
  )
  
  if (hasScheduleConflict) return false
  
  // 檢查是否與停機時段衝突
  const hasDowntimeConflict = downtimeSlots.some(slot =>
    slot.machineId === machineId &&
    slot.startHour < endHour &&
    slot.endHour > startHour
  )
  
  return !hasDowntimeConflict
}

/**
 * 為訂單找到最早可用的時間段
 */
export function findEarliestAvailableSlot(
  machineId: number,
  duration: number,
  startFrom: number,
  endBefore: number,
  existingSchedules: SchedulingResult[],
  downtimeSlots: { machineId: number; startHour: number; endHour: number }[]
): { startHour: number; endHour: number } | null {
  // 獲取該機台的所有佔用時段（排程 + 停機）
  const occupiedSlots = [
    ...existingSchedules
      .filter(s => s.machineId === machineId)
      .map(s => ({ start: s.startHour, end: s.endHour })),
    ...downtimeSlots
      .filter(s => s.machineId === machineId)
      .map(s => ({ start: s.startHour, end: s.endHour }))
  ].sort((a, b) => a.start - b.start)
  
  let currentStart = startFrom
  
  for (const slot of occupiedSlots) {
    // 如果當前位置到下個佔用時段之間有足夠空間
    if (currentStart + duration <= slot.start) {
      return {
        startHour: currentStart,
        endHour: currentStart + duration
      }
    }
    // 移動到該時段結束後
    currentStart = Math.max(currentStart, slot.end)
  }
  
  // 檢查最後一個空檔
  if (currentStart + duration <= endBefore) {
    return {
      startHour: currentStart,
      endHour: currentStart + duration
    }
  }
  
  return null
}

/**
 * 執行 AI 自動排程
 */
export function executeAutoScheduling(
  orders: Order[],
  config: SchedulingConfig,
  history: MachineProductHistory[],
  downtimeSlots: { machineId: number; startHour: number; endHour: number }[]
): SchedulingResult[] {
  // 1. 先根據合併策略處理訂單
  const processedOrders = mergeOrders(orders, config.mergeStrategy)
  
  // 2. 按交期排序（急單優先）
  const sortedOrders = [...processedOrders].sort((a, b) => {
    const dateA = new Date(a.due_date).getTime()
    const dateB = new Date(b.due_date).getTime()
    if (dateA !== dateB) return dateA - dateB
    // 交期相同時，優先級高的優先
    return b.priority - a.priority
  })
  
  const results: SchedulingResult[] = []
  
  // 3. 為每個訂單分配機台和時間
  for (const order of sortedOrders) {
    // 選擇最佳機台
    const { machineId, reason } = selectBestMachine(
      order.product_code,
      config.strategy,
      history,
      config.availableMachines
    )
    
    // 計算預估生產時間
    const duration = estimateProductionTime(
      order.quantity,
      order.product_code,
      history,
      machineId
    )
    
    // 尋找最早可用時段
    const slot = findEarliestAvailableSlot(
      machineId,
      duration,
      config.startHour,
      config.endHour,
      results,
      downtimeSlots
    )
    
    if (slot) {
      results.push({
        machineId,
        startHour: slot.startHour,
        endHour: slot.endHour,
        orderId: order.order_number,
        reason
      })
    } else {
      // 如果該機台沒有空位，嘗試其他機台
      let assigned = false
      for (const altMachineId of config.availableMachines) {
        if (altMachineId === machineId) continue
        
        const altSlot = findEarliestAvailableSlot(
          altMachineId,
          duration,
          config.startHour,
          config.endHour,
          results,
          downtimeSlots
        )
        
        if (altSlot) {
          results.push({
            machineId: altMachineId,
            startHour: altSlot.startHour,
            endHour: altSlot.endHour,
            orderId: order.order_number,
            reason: `${reason}（最佳機台已滿，改用機台 ${altMachineId}）`
          })
          assigned = true
          break
        }
      }
      
      if (!assigned) {
        console.warn(`無法為訂單 ${order.order_number} 找到可用時段`)
      }
    }
  }
  
  return results
}
