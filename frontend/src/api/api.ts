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

  async deleteOrder(id: string): Promise<void> {
    const response = await fetch(`${API_BASE_URL}/orders/${id}`, {
      method: 'DELETE'
    })
    if (!response.ok) throw new Error('Failed to delete order')
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
  }
}
