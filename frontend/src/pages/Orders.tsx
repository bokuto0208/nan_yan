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
  const [searchTerm, setSearchTerm] = useState('')

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

  // 搜尋過濾函數
  function filterOrders(groups: ReturnType<typeof groupOrdersByNumber>) {
    if (!searchTerm.trim()) return groups
    
    const term = searchTerm.toLowerCase()
    return groups.filter(group => {
      // 搜尋訂單號
      if (group.orderNumber.toLowerCase().includes(term)) return true
      
      // 搜尋客戶名稱
      if (group.firstOrder.customer_name?.toLowerCase().includes(term)) return true
      
      // 搜尋品號
      const hasMatchingProduct = group.orders.some(order => 
        order.product_code.toLowerCase().includes(term)
      )
      if (hasMatchingProduct) return true
      
      // 搜尋子件代碼
      const hasMatchingComponent = group.orders.some(order =>
        order.products?.some((product: any) =>
          product.components?.some((comp: any) =>
            comp.component_code.toLowerCase().includes(term)
          )
        )
      )
      if (hasMatchingComponent) return true
      
      return false
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

  async function handleDelete(orderNumber: string) {
    if (!confirm(`確定要刪除訂單 ${orderNumber} 嗎？此操作將刪除該訂單號的所有記錄。`)) return
    await api.deleteOrder(orderNumber)
    load()
  }

  async function handleDeleteAll() {
    if (!confirm('⚠️ 確定要刪除所有訂單嗎？\n\n此操作將刪除:\n- 所有訂單\n- 所有元件排程\n- 所有排程區塊\n- 所有產品記錄\n\n此操作無法復原！')) return
    
    if (!confirm('再次確認：真的要刪除所有訂單嗎？')) return
    
    try {
      setLoading(true)
      const result = await api.deleteAllOrders()
      alert(`刪除成功！\n\n訂單: ${result.deleted.orders} 筆\n元件排程: ${result.deleted.component_schedules} 筆\n排程區塊: ${result.deleted.schedule_blocks} 筆\n產品記錄: ${result.deleted.products} 筆`)
      load()
    } catch (error: any) {
      alert(`刪除失敗: ${error.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleImportExcel(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    
    try {
      setLoading(true)
      const result = await api.importOrdersExcel(file)
      let message = `匯入完成！\n新增: ${result.imported} 筆\n更新: ${result.updated} 筆\n跳過: ${result.skipped} 筆`
      
      if (result.warnings && result.warnings.length > 0) {
        message += '\n\n⚠️ 警示訊息:\n' + result.warnings.join('\n')
      }
      
      alert(message)
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
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {/* 搜尋框 */}
          <input
            type="text"
            placeholder="🔍 搜尋訂單號、客戶、品號、子件..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              padding: '8px 12px',
              borderRadius: '6px',
              border: '1px solid rgba(255,255,255,0.2)',
              background: 'rgba(255,255,255,0.05)',
              color: '#fff',
              fontSize: '14px',
              width: '280px',
              outline: 'none'
            }}
          />
          {searchTerm && (
            <button 
              onClick={() => setSearchTerm('')}
              style={{ 
                padding: '8px 12px',
                fontSize: '14px',
                background: 'rgba(255,255,255,0.1)',
                border: '1px solid rgba(255,255,255,0.2)',
                borderRadius: '6px',
                color: '#fff',
                cursor: 'pointer'
              }}
            >
              清除
            </button>
          )}
          <button onClick={() => { setShowForm(!showForm); setEditing(null) }}>{showForm ? '關閉' : '新增訂單'}</button>
          <button style={{ marginLeft: 8 }} onClick={() => document.getElementById('excel-upload')?.click()}>
            匯入 Excel
          </button>
          <button 
            style={{ marginLeft: 8, backgroundColor: '#dc3545', color: 'white' }} 
            onClick={handleDeleteAll}
          >
            🗑️ 刪除所有訂單
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
          {(() => {
            const groupedOrders = groupOrdersByNumber(orders)
            const filteredOrders = filterOrders(groupedOrders)
            
            // 顯示搜尋結果統計
            if (searchTerm && filteredOrders.length !== groupedOrders.length) {
              return (
                <>
                  <div style={{
                    padding: '12px 16px',
                    background: 'rgba(30, 160, 233, 0.1)',
                    border: '1px solid rgba(30, 160, 233, 0.3)',
                    borderRadius: '8px',
                    marginBottom: '16px',
                    color: '#1ea0e9',
                    fontSize: '14px'
                  }}>
                    🔍 找到 <strong>{filteredOrders.length}</strong> 筆符合「{searchTerm}」的訂單
                    （共 {groupedOrders.length} 筆訂單）
                  </div>
                  {filteredOrders.length === 0 ? (
                    <div style={{
                      padding: '40px',
                      textAlign: 'center',
                      color: 'rgba(255,255,255,0.5)',
                      fontSize: '14px'
                    }}>
                      😕 沒有找到符合的訂單
                    </div>
                  ) : (
                    filteredOrders.map((group) => renderOrderCard(group))
                  )}
                </>
              )
            }
            
            return filteredOrders.map((group) => renderOrderCard(group))
          })()}
        </div>
      )}
    </div>
  )
  
  // 渲染訂單卡片的函數
  function renderOrderCard(group: ReturnType<typeof groupOrdersByNumber>[0]) {
    return (
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
                  <button onClick={() => handleDelete(group.orderNumber)} style={{ marginLeft: 6 }}>刪除</button>
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
                            {order.inventory_quantity !== undefined && order.inventory_quantity !== null && (
                              <span className="product-inventory" style={{ color: '#3b82f6' }}>庫存：{order.inventory_quantity}</span>
                            )}
                            {order.undelivered_quantity !== undefined && order.undelivered_quantity !== null && (
                              <span className="product-undelivered">未交數量：{order.undelivered_quantity}</span>
                            )}
                          </div>
                        </div>
                        
                        {order.products && order.products.length > 0 ? (
                          <div className="components-list">
                            {order.warning && (
                              <div style={{ 
                                padding: '8px 12px', 
                                backgroundColor: '#fff3cd', 
                                border: '1px solid #ffc107',
                                borderRadius: '4px',
                                marginBottom: '12px',
                                color: '#856404'
                              }}>
                                ⚠️ 品號 {order.product_code} 有排程資料上的缺失! (原因: {order.warning})
                              </div>
                            )}
                            <table className="components-table">
                              <thead>
                                <tr>
                                  <th>子件代碼</th>
                                  <th>子件數量/生產回次</th>
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
    )
  }
}
