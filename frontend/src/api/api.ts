import { Order } from '../types'

const API_BASE_URL = 'http://localhost:8000/api'

export const api = {
  // 訂單相關 API
  async getOrders(): Promise<Order[]> {
    const response = await fetch(`${API_BASE_URL}/orders`)
    if (!response.ok) throw new Error('Failed to fetch orders')
    return response.json()
  },

  async getOrder(id: string): Promise<Order> {
    const response = await fetch(`${API_BASE_URL}/orders/${id}`)
    if (!response.ok) throw new Error('Failed to fetch order')
    return response.json()
  },

  async createOrder(order: Omit<Order, 'id' | 'created_at' | 'updated_at'>): Promise<Order> {
    const response = await fetch(`${API_BASE_URL}/orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(order)
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to create order')
    }
    return response.json()
  },

  async updateOrder(id: string, order: Partial<Order>): Promise<Order> {
    const response = await fetch(`${API_BASE_URL}/orders/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(order)
    })
    if (!response.ok) throw new Error('Failed to update order')
    return response.json()
  },

  async deleteOrder(orderNumber: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/orders/${orderNumber}`, {
      method: 'DELETE'
    })
    if (!response.ok) throw new Error('Failed to delete order')
  },

  async deleteAllOrders(): Promise<{message: string, deleted: {orders: number, component_schedules: number, schedule_blocks: number, products: number}}> {
    const response = await fetch(`${API_BASE_URL}/orders/all/delete`, {
      method: 'DELETE'
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to delete all orders')
    }
    return response.json()
  },

  async importOrdersExcel(file: File): Promise<{imported: number, updated: number, skipped: number, warnings?: string[]}> {
    const formData = new FormData()
    formData.append('file', file)
    
    const response = await fetch(`${API_BASE_URL}/orders/import-excel`, {
      method: 'POST',
      body: formData
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to import Excel')
    }
    return response.json()
  },

  // 停機時段相關 API
  async getDowntimes(date?: string): Promise<any[]> {
    const url = date ? `${API_BASE_URL}/downtimes?date=${date}` : `${API_BASE_URL}/downtimes`
    const response = await fetch(url)
    if (!response.ok) throw new Error('Failed to fetch downtimes')
    return response.json()
  },

  async createDowntime(downtime: {
    machine_id: string
    start_hour: number
    end_hour: number
    date: string
    reason?: string
  }): Promise<any> {
    const response = await fetch(`${API_BASE_URL}/downtimes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(downtime)
    })
    if (!response.ok) throw new Error('Failed to create downtime')
    return response.json()
  },

  async deleteDowntime(id: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/downtimes/${id}`, {
      method: 'DELETE'
    })
    if (!response.ok) throw new Error('Failed to delete downtime')
  },

  // 機台產品歷史數據 API
  async getMachineHistory(machineId?: number, productCode?: string): Promise<any[]> {
    const params = new URLSearchParams()
    if (machineId) params.append('machine_id', machineId.toString())
    if (productCode) params.append('product_code', productCode)
    
    const url = params.toString() 
      ? `${API_BASE_URL}/machine-history?${params}`
      : `${API_BASE_URL}/machine-history`
    
    const response = await fetch(url)
    if (!response.ok) throw new Error('Failed to fetch machine history')
    return response.json()
  },

  async bootstrapMachineHistory(): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/machine-history/bootstrap`, {
      method: 'POST'
    })
    if (!response.ok) throw new Error('Failed to bootstrap machine history')
  },

  // 機台相關 API
  async getMachines(area?: string): Promise<{ machine_id: string; area: string }[]> {
    const url = area ? `${API_BASE_URL}/machines?area=${area}` : `${API_BASE_URL}/machines`
    const response = await fetch(url)
    if (!response.ok) throw new Error('Failed to fetch machines')
    return response.json()
  },

  async getAreas(): Promise<{ areas: string[] }> {
    const response = await fetch(`${API_BASE_URL}/machines/areas`)
    if (!response.ok) throw new Error('Failed to fetch areas')
    return response.json()
  },

  // 元件相關 API
  async getComponents(): Promise<any[]> {
    const response = await fetch(`${API_BASE_URL}/components`)
    if (!response.ok) throw new Error('Failed to fetch components')
    return response.json()
  },

  async createComponent(component: {
    component_code: string
    component_name: string
    unit?: string
    estimated_production_time?: number
  }): Promise<any> {
    const response = await fetch(`${API_BASE_URL}/components`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(component)
    })
    if (!response.ok) throw new Error('Failed to create component')
    return response.json()
  },

  // BOM相關 API
  async getBOM(productCode?: string): Promise<any[]> {
    const url = productCode 
      ? `${API_BASE_URL}/bom?product_code=${productCode}`
      : `${API_BASE_URL}/bom`
    const response = await fetch(url)
    if (!response.ok) throw new Error('Failed to fetch BOM')
    return response.json()
  },

  async createBOM(bom: {
    product_code: string
    component_code: string
    quantity_per_unit: number
  }): Promise<any> {
    const response = await fetch(`${API_BASE_URL}/bom`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bom)
    })
    if (!response.ok) throw new Error('Failed to create BOM')
    return response.json()
  },

  // 訂單詳細資訊 (包含元件)
  async getOrderWithComponents(orderId: string): Promise<any> {
    const response = await fetch(`${API_BASE_URL}/orders/${orderId}/detail`)
    if (!response.ok) throw new Error('Failed to fetch order detail')
    return response.json()
  },

  async getOrdersWithComponents(): Promise<any[]> {
    const response = await fetch(`${API_BASE_URL}/orders-with-components`)
    if (!response.ok) throw new Error('Failed to fetch orders with components')
    return response.json()
  },

  async expandOrderComponents(orderId: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/orders/${orderId}/expand-components`, {
      method: 'POST'
    })
    if (!response.ok) throw new Error('Failed to expand order components')
  },

  // 工作日曆相關 API
  async getWorkCalendar(year?: number, month?: number): Promise<any[]> {
    let url = `${API_BASE_URL}/work-calendar`
    if (year && month) {
      url += `?year=${year}&month=${month}`
    }
    const response = await fetch(url)
    if (!response.ok) throw new Error('Failed to fetch work calendar')
    return response.json()
  },

  async upsertWorkCalendarDay(data: {
    work_date: string
    work_hours: number
    start_time: string
    note?: string
  }): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/work-calendar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    if (!response.ok) throw new Error('Failed to save work calendar day')
  },

  async batchUpsertWorkCalendar(data: {
    days: Array<{
      work_date: string
      work_hours: number
      start_time: string
      note?: string
    }>
  }): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/work-calendar/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    })
    if (!response.ok) throw new Error('Failed to batch save work calendar')
  },

  // 排程相關 API
  async runScheduling(config: {
    order_ids?: string[]
    merge_enabled?: boolean
    merge_window_weeks?: number
    time_threshold_pct?: number
    reschedule_all?: boolean
    scheduling_mode?: 'normal' | 'fill_all_machines'
  }): Promise<{
    success: boolean
    message: string
    blocks: Array<{
      block_id: string
      machine_id: string
      mold_code: string
      start_time: string
      end_time: string
      mo_ids: string[]
      component_codes: string[]
      product_display: string
      status: string
      is_merged: boolean
    }>
    scheduled_mos: string[]
    failed_mos: string[]
    total_mos: number
    on_time_count: number
    late_count: number
    total_lateness_days: number
    changeover_count: number
    delay_reports: any[]
    change_log: any[]
    execution_time_seconds: number
  }> {
    const response = await fetch(`${API_BASE_URL}/scheduling/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to run scheduling')
    }
    return response.json()
  },

  async getSchedulingStatus(): Promise<{
    pending_orders: number
    scheduled_orders: number
    last_schedule_time: string | null
  }> {
    const response = await fetch(`${API_BASE_URL}/scheduling/status`)
    if (!response.ok) throw new Error('Failed to get scheduling status')
    return response.json()
  },

  async getScheduledComponents(date?: string, machineId?: string): Promise<{
    schedules: Array<{
      id: string
      orderId: string
      originalOrderId?: string  // 資料庫 UUID
      productId: string
      moldCode?: string         // 模具編號
      machineId: string
      startHour: number
      endHour: number
      scheduledDate: string
      status: string
      aiLocked: boolean
      isSplit?: boolean
      splitPart?: number
      totalSplits?: number
    }>
  }> {
    const params = new URLSearchParams()
    if (date) params.append('date', date)
    if (machineId) params.append('machine_id', machineId)
    
    const url = `${API_BASE_URL}/scheduling/schedules${params.toString() ? '?' + params.toString() : ''}`
    const response = await fetch(url)
    if (!response.ok) throw new Error('Failed to get scheduled components')
    return response.json()
  },

  async updateScheduledComponents(
    updates: Array<{
      id: string
      orderId: string
      productId: string
      startHour: number
      endHour: number
      machineId: string
      scheduledDate: string
      status?: string
      aiLocked?: boolean
      isModified?: boolean
    }>,
    deletedIds: string[] = []
  ): Promise<{
    success: boolean
    updated_count: number
    errors: string[]
  }> {
    const response = await fetch(`${API_BASE_URL}/scheduling/schedules/batch`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ updates, deletedIds })
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Failed to update schedules')
    }
    return response.json()
  },

  // 模具機台適配性相關 API
  async getCompatibleMachines(moldCode: string): Promise<{mold_code: string, compatible_machines: string[]}> {
    const response = await fetch(`${API_BASE_URL}/mold/${moldCode}/compatible-machines`)
    if (!response.ok) throw new Error('Failed to get compatible machines')
    return response.json()
  },

  async checkMoldMachineCompatibility(moldCode: string, machineId: string): Promise<{mold_code: string, machine_id: string, compatible: boolean}> {
    const response = await fetch(`${API_BASE_URL}/mold/check-compatibility/${moldCode}/${machineId}`)
    if (!response.ok) throw new Error('Failed to check compatibility')
    return response.json()
  },

  // === 聊天助理 API ===
  async chat(question: string, context?: string): Promise<{ answer: string; model: string }> {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, context })
    })
    if (!response.ok) {
      const error = await response.text()
      throw new Error(`Chat failed: ${error}`)
    }
    return response.json()
  }
}
