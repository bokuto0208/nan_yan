export type OrderStatus = 'PENDING' | 'SCHEDULED' | 'DONE'

export interface Order {
  id: string
  order_number: string
  customer_name: string
  product_code: string
  quantity: number
  due_date: string // ISO date
  priority: number
  status: OrderStatus
  scheduled_date?: string // ISO date for production
  scheduled_start_time?: string // HH:MM format
  scheduled_end_time?: string // HH:MM format (auto-calculated)
}

export interface Component {
  id: string
  component_code: string
  component_name: string
  unit: string
  estimated_production_time: number
  created_at: string
}

export interface BOM {
  id: number
  product_code: string
  component_code: string
  quantity_per_unit: number
  created_at: string
}

export interface ComponentSchedule {
  id: string
  order_id: string
  component_code: string
  quantity: number
  scheduled_date?: string
  scheduled_start_time?: string
  scheduled_end_time?: string
  machine_id?: string
  status: string
  created_at: string
  updated_at: string
}

export interface ProductWithComponents {
  product_code: string
  quantity: number
  components: {
    component_code: string
    quantity: number
    cavity_count: number
    status: string
  }[]
}

export interface OrderWithComponents {
  id: string
  order_number: string
  customer_name: string
  customer_id?: string
  product_code: string
  quantity: number
  undelivered_quantity?: number
  due_date: string
  priority: number
  status: string
  created_at: string
  updated_at: string
  products: ProductWithComponents[]
}
