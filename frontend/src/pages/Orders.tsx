import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom'
import { Order, OrderWithComponents, ComponentSchedule } from '../types'
import { api } from '../api/api'
import OrderForm from '../components/OrderForm'

export default function OrdersPage() {
  const [orders, setOrders] = useState<OrderWithComponents[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<Order | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [expandedOrders, setExpandedOrders] = useState<Set<string>>(new Set())

  async function load() {
    setLoading(true)
    const res = await api.getOrdersWithComponents()
    setOrders(res)
    setLoading(false)
  }

  // 將訂單按訂單號分組
  function groupOrdersByNumber(orders: OrderWithComponents[]) {
    const grouped = new Map<string, OrderWithComponents[]>()
    
    orders.forEach(order => {
      const existing = grouped.get(order.order_number) || []
      grouped.set(order.order_number, [...existing, order])
    })
    
    return Array.from(grouped.entries()).map(([orderNumber, orderList]) => ({
      orderNumber,
      orders: orderList,
      // 使用第一筆訂單的基本資訊
      firstOrder: orderList[0]
    }))
  }

  function toggleOrderExpanded(orderNumber: string) {
    setExpandedOrders(prev => {
      const newSet = new Set(prev)
      if (newSet.has(orderNumber)) {
        newSet.delete(orderNumber)
      } else {
        newSet.add(orderNumber)
      }
      return newSet
    })
  }

  useEffect(() => {
    load()
  }, [])

  async function handleCreate(data: Omit<Order, 'id'>) {
    await api.createOrder(data as any)
    setShowForm(false)
    alert('訂單已新增！系統已自動根據 BOM 拆解成子件。')
    load()
  }

  async function handleUpdate(id: string, data: Partial<Order>) {
    await api.updateOrder(id, data)
    setEditing(null)
    setShowForm(false)
    load()
  }

  async function handleDelete(id: string) {
    if (!confirm('確定要刪除此訂單嗎？')) return
    await api.deleteOrder(id)
    load()
  }

  async function handleImportExcel(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    
    try {
      setLoading(true)
      const result = await api.importOrdersExcel(file)
      alert(`匯入完成！\n新增: ${result.imported} 筆\n更新: ${result.updated} 筆\n跳過: ${result.skipped} 筆`)
      load()
    } catch (error: any) {
      alert(`匯入失敗: ${error.message}`)
    } finally {
      setLoading(false)
      // 清空 input
      event.target.value = ''
    }
  }

  // Calculate estimated production time for component
  const formatProductionTime = (scheduled_start_time?: string, scheduled_end_time?: string): string => {
    if (!scheduled_start_time || !scheduled_end_time) return '未設定'
    return `${scheduled_start_time} - ${scheduled_end_time}`
  }

  return (
    <div className="page">
      <div className="page-header">
        <h2>訂單管理</h2>
        <div>
          <button onClick={() => { setShowForm(!showForm); setEditing(null) }}>{showForm ? '關閉' : '新增訂單'}</button>
          <button style={{ marginLeft: 8 }} onClick={() => document.getElementById('excel-upload')?.click()}>
            匯入 Excel
          </button>
          <input
            id="excel-upload"
            type="file"
            accept=".xlsx,.xls"
            style={{ display: 'none' }}
            onChange={handleImportExcel}
          />
        </div>
      </div>

      {(showForm || editing) && ReactDOM.createPortal(
        <div className="modal-overlay" onClick={() => { setShowForm(false); setEditing(null); }}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            {showForm && !editing && (
              <OrderForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
            )}
            {editing && (
              <OrderForm
                initial={editing}
                onSubmit={(data) => handleUpdate(editing.id, data as Partial<Order>)}
                onCancel={() => setEditing(null)}
                submitLabel="更新"
              />
            )}
          </div>
        </div>,
        document.getElementById('modal-root')!
      )}

      {loading ? <p>載入中...</p> : (
        <div className="orders-container">
          {groupOrdersByNumber(orders).map((group) => (
            <div key={group.orderNumber} className="order-card">
              <div className="order-header" onClick={() => toggleOrderExpanded(group.orderNumber)}>
                <div className="order-info">
                  <span className="order-expand-icon">
                    {expandedOrders.has(group.orderNumber) ? '▼' : '▶'}
                  </span>
                  <div className="order-main-info">
                    <span className="order-number">{group.orderNumber}</span>
                    <span className="order-customer">{group.firstOrder.customer_name}</span>
                    <span className="order-due-date">交期: {group.firstOrder.due_date}</span>
                  </div>
                </div>
                <div className="order-actions" onClick={(e) => e.stopPropagation()}>
                  <button onClick={() => { setEditing(group.firstOrder as any); setShowForm(false) }}>編輯</button>
                  <button onClick={() => handleDelete(group.firstOrder.id)} style={{ marginLeft: 6 }}>刪除</button>
                </div>
              </div>
              
              {expandedOrders.has(group.orderNumber) && (
                <div className="components-section">
                  <div className="products-list">
                    {group.orders.map((order) => (
                      <div key={order.id} className="product-item">
                        <div className="product-header">
                          <div className="product-info">
                            <span className="product-label">品號：</span>
                            <span className="product-code">{order.product_code}</span>
                            <span className="product-quantity">訂單數量：{order.quantity}</span>
                            {order.undelivered_quantity !== undefined && order.undelivered_quantity !== null && (
                              <span className="product-undelivered">未交數量：{order.undelivered_quantity}</span>
                            )}
                          </div>
                        </div>
                        
                        {order.products && order.products.length > 0 ? (
                          <div className="components-list">
                            <table className="components-table">
                              <thead>
                                <tr>
                                  <th>子件代碼</th>
                                  <th>子件數量</th>
                                  <th>穴數</th>
                                  <th>狀態</th>
                                </tr>
                              </thead>
                              <tbody>
                                {order.products.flatMap((product: any) => 
                                  product.components?.map((comp: any, compIdx: number) => (
                                    <tr key={`${product.product_code}-${compIdx}`}>
                                      <td style={{ fontWeight: 600, color: '#10b981' }}>{comp.component_code}</td>
                                      <td>{comp.quantity}</td>
                                      <td>{comp.cavity_count}</td>
                                      <td>
                                        <span className={`status-badge status-${comp.status.toLowerCase()}`}>
                                          {comp.status}
                                        </span>
                                      </td>
                                    </tr>
                                  )) || []
                                )}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <div className="no-components" style={{ marginLeft: '20px', fontSize: '13px', color: '#888' }}>
                            此品號無對應的子件（BOM表中無資料）
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
