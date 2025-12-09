import { Order } from '../types'

const STORAGE_KEY = 'eps_orders'

function readAll(): Order[] {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return []
  try {
    return JSON.parse(raw) as Order[]
  } catch {
    return []
  }
}

function writeAll(items: Order[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
}

export const mockApi = {
  getOrders: async (): Promise<Order[]> => {
    // simulate latency
    await new Promise((r) => setTimeout(r, 120))
    return readAll()
  },

  createOrder: async (o: Omit<Order, 'id'>): Promise<Order> => {
    const items = readAll()
    const id = Date.now().toString()
    const newItem: Order = { id, ...o }
    items.push(newItem)
    writeAll(items)
    return newItem
  },

  updateOrder: async (id: string, patch: Partial<Order>): Promise<Order | null> => {
    const items = readAll()
    const idx = items.findIndex((it) => it.id === id)
    if (idx === -1) return null
    const updated = { ...items[idx], ...patch }
    items[idx] = updated
    writeAll(items)
    return updated
  },

  deleteOrder: async (id: string): Promise<boolean> => {
    const items = readAll()
    const filtered = items.filter((it) => it.id !== id)
    writeAll(filtered)
    return true
  },

  bootstrapSampleData: async (): Promise<void> => {
    const sample: Order[] = [
      {
        id: '1',
        order_number: 'ORD-001',
        customer_name: 'ACME Corp',
        product_code: 'P-100',
        quantity: 500,
        due_date: new Date(Date.now() + 1000 * 60 * 60 * 24 * 7).toISOString().slice(0, 10),
        priority: 2,
        status: 'PENDING'
      },
      {
        id: '2',
        order_number: 'ORD-002',
        customer_name: 'Beta Ltd',
        product_code: 'P-200',
        quantity: 200,
        due_date: new Date(Date.now() + 1000 * 60 * 60 * 24 * 3).toISOString().slice(0, 10),
        priority: 1,
        status: 'PENDING'
      }
    ]
    writeAll(sample)
  }
}
