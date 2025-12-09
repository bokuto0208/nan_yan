import React, { useState } from 'react'
import { Order } from '../types'

type Props = {
  initial?: Partial<Order>
  onSubmit: (data: Omit<Order, 'id'>) => void
  onCancel?: () => void
  submitLabel?: string
}

type ProductItem = {
  id: string
  product_code: string
  quantity: number
}

export default function OrderForm({ initial = {}, onSubmit, onCancel, submitLabel = '保存' }: Props) {
  const [orderNumber, setOrderNumber] = useState(initial.order_number ?? '')
  const [customerName, setCustomerName] = useState(initial.customer_name ?? '')
  const [dueDate, setDueDate] = useState(initial.due_date ?? '')
  
  // 從 initial 讀取現有的產品資料
  const initialProducts = (initial as any).products?.map((p: any, index: number) => ({
    id: `${index + 1}`,
    product_code: p.product_code || '',
    quantity: p.quantity || 0
  })) || [{ id: '1', product_code: '', quantity: 0 }]
  
  const [products, setProducts] = useState<ProductItem[]>(initialProducts)

  function addProduct() {
    setProducts([...products, { 
      id: Date.now().toString(), 
      product_code: '', 
      quantity: 0
    }])
  }

  function removeProduct(id: string) {
    if (products.length > 1) {
      setProducts(products.filter(p => p.id !== id))
    }
  }

  function updateProduct(id: string, field: keyof ProductItem, value: string | number) {
    setProducts(products.map(p => 
      p.id === id ? { ...p, [field]: value } : p
    ))
  }

  function submit(e: React.FormEvent) {
    e.preventDefault()
    
    // 驗證所有產品都有填寫
    if (products.some(p => !p.product_code || p.quantity <= 0)) {
      alert('請填寫所有產品的資訊')
      return
    }
    
    // 發送包含產品列表的訂單資料
    const orderData: any = {
      order_number: orderNumber,
      customer_name: customerName,
      due_date: dueDate,
      priority: 3,
      status: 'PENDING',
      products: products.map(p => ({
        product_code: p.product_code,
        quantity: p.quantity
      }))
    }
    
    onSubmit(orderData)
  }

  return (
    <form className="order-form-new" onSubmit={submit}>
      {/* 上方：訂單基本資訊 */}
      <div className="order-form-header">
        <div className="form-field">
          <label>訂單號</label>
          <input 
            value={orderNumber} 
            onChange={(e) => setOrderNumber(e.target.value)} 
            placeholder="ORD-001"
            required 
          />
        </div>
        <div className="form-field">
          <label>客戶代號</label>
          <input 
            value={customerName} 
            onChange={(e) => setCustomerName(e.target.value)} 
            placeholder="CUSTOMER-A"
            required 
          />
        </div>
        <div className="form-field">
          <label>交期</label>
          <input 
            type="date" 
            value={dueDate} 
            onChange={(e) => setDueDate(e.target.value)} 
            required 
          />
        </div>
      </div>

      {/* 下方：產品列表 */}
      <div className="products-section">
        <h3>產品列表</h3>
        {products.map((product) => (
          <div key={product.id} className="product-item-row">
            <div className="product-field">
              <label>品號</label>
              <input 
                value={product.product_code}
                onChange={(e) => updateProduct(product.id, 'product_code', e.target.value)}
                placeholder="P001"
                required
              />
            </div>
            <div className="product-field">
              <label>數量</label>
              <input 
                type="number"
                value={product.quantity || ''}
                onChange={(e) => updateProduct(product.id, 'quantity', Number(e.target.value))}
                placeholder="100"
                required
              />
            </div>
            <button 
              type="button" 
              className="remove-product-btn"
              onClick={() => removeProduct(product.id)}
              title="移除此產品"
            >
              ✕
            </button>
          </div>
        ))}
        
        <button 
          type="button" 
          className="add-product-btn"
          onClick={addProduct}
        >
          <span className="plus-icon">+</span>
          <span>新增產品</span>
        </button>
      </div>

      <div className="form-actions">
        <button type="button" className="cancel-btn" onClick={onCancel}>取消</button>
        <button type="submit" className="submit-btn">{submitLabel}</button>
      </div>
    </form>
  )
}
