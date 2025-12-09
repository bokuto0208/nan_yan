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

  function toggleOrderExpanded(orderId: string) {
    setExpandedOrders(prev => {
      const newSet = new Set(prev)
      if (newSet.has(orderId)) {
        newSet.delete(orderId)
      } else {
        newSet.add(orderId)
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
          {orders.map((order) => (
            <div key={order.id} className="order-card">
              <div className="order-header" onClick={() => toggleOrderExpanded(order.id)}>
                <div className="order-info">
                  <span className="order-expand-icon">
                    {expandedOrders.has(order.id) ? '▼' : '▶'}
                  </span>
                  <div className="order-main-info">
                    <span className="order-number">{order.order_number}</span>
                    <span className="order-customer">{order.customer_name}</span>
                    <span className="order-due-date">交期: {order.due_date}</span>
                  </div>
                </div>
                <div className="order-actions" onClick={(e) => e.stopPropagation()}>
                  <button onClick={() => { setEditing(order); setShowForm(false) }}>編輯</button>
                  <button onClick={() => handleDelete(order.id)} style={{ marginLeft: 6 }}>刪除</button>
                </div>
              </div>
              
              {expandedOrders.has(order.id) && (
                <div className="components-section">
                  {!order.products || order.products.length === 0 ? (
                    <div className="no-components">
                      <p>此訂單無產品資料</p>
                    </div>
                  ) : (
                    <div className="products-list">
                      {order.products.map((product: any, idx: number) => (
                        <div key={idx} className="product-item">
                          <div className="product-header">
                            <div className="product-info">
                              <span className="product-label">品號：</span>
                              <span className="product-code">{product.product_code}</span>
                              <span className="product-quantity">數量：{product.quantity}</span>
                            </div>
                          </div>
                          
                          {product.components && product.components.length > 0 ? (
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
                                  {product.components.map((comp: any, compIdx: number) => (
                                    <tr key={compIdx}>
                                      <td style={{ fontWeight: 600, color: '#10b981' }}>{comp.component_code}</td>
                                      <td>{comp.quantity}</td>
                                      <td>{comp.cavity_count}</td>
                                      <td>
                                        <span className={`status-badge status-${comp.status.toLowerCase()}`}>
                                          {comp.status}
                                        </span>
                                      </td>
                                    </tr>
                                  ))}
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
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
