import React, { useState } from 'react'
import OrdersPage from './pages/Orders'
import Home from './pages/Home'
import SchedulingPage from './pages/Scheduling'
import DispatchOrderPage from './pages/DispatchOrder'


export default function App() {
  const [route, setRoute] = useState<
    'home' | 'orders' | 'machines' | 'dispatch' | 'scenarios'
  >('dispatch')

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)


  return (
    <div className="layout">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <button 
          className="sidebar-toggle"
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          title={sidebarCollapsed ? '展開選單' : '收納選單'}
        >
          {sidebarCollapsed ? '☰' : '✕'}
        </button>
        
        <div className="sidebar-content">
          <button className={route === 'home' ? 'active' : ''} onClick={() => setRoute('home')}>
            <span className="icon">🏠</span>
            {!sidebarCollapsed && <span className="text">首頁（測試）</span>}

          </button>
          <button className={route === 'orders' ? 'active' : ''} onClick={() => setRoute('orders')}>
            <span className="icon">📋</span>
            {!sidebarCollapsed && <span className="text">訂單</span>}
          </button>
          <button className={route === 'machines' ? 'active' : ''} onClick={() => setRoute('machines')}>
            <span className="icon">⚙️</span>
            {!sidebarCollapsed && <span className="text">生產排程</span>}
          </button>
          <button className={route === 'dispatch' ? 'active' : ''} onClick={() => setRoute('dispatch')}>
  <span className="icon">🧾</span>
  {!sidebarCollapsed && <span className="text">派工單</span>}
</button>

        </div>
      </aside>

      <div className="separator" />

      <div className="content-area">
       {route === 'home' && <Home />}
{route === 'orders' && <OrdersPage />}
{route === 'machines' && <SchedulingPage />}
{route === 'dispatch' && <DispatchOrderPage />}
{route === 'scenarios' && <p>Scenarios (placeholder)</p>}

      </div>

      {/* footer removed per design */}
    </div>
  )
}
