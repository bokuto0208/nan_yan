import React, { useState } from 'react'
import OrdersPage from './pages/Orders'
import Home from './pages/Home'
import SchedulingPage from './pages/Scheduling'
import DispatchOrderPage from './pages/DispatchOrder'
import WorkCalendar from './pages/WorkCalendar'
import AssistantChatPage from './pages/AssistantChat'
import FloatingChat from './components/FloatingChat'



export default function App() {
  const [route, setRoute] = useState<'home' | 'orders' | 'machines' | 'dispatch' | 'workcalendar' | 'assistant' | 'scenarios'>('home')
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
            {!sidebarCollapsed && <span className="text">首頁</span>}
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
            {!sidebarCollapsed && <span className="text">報完工單</span>}
          </button>
          <button className={route === 'workcalendar' ? 'active' : ''} onClick={() => setRoute('workcalendar')}>
            <span className="icon">📅</span>
            {!sidebarCollapsed && <span className="text">工作日曆</span>}
          </button>
          <button className={route === 'assistant' ? 'active' : ''} onClick={() => setRoute('assistant')}>
            <span className="icon">🤖</span>
            {!sidebarCollapsed && <span className="text">聊天助理</span>}
          </button>
        </div>
      </aside>

      <div className="separator" />

      <div className="content-area">
        {route === 'home' && <Home />}
        {route === 'orders' && <OrdersPage />}
        {route === 'machines' && <SchedulingPage />}
        {route === 'dispatch' && <DispatchOrderPage />}
        {route === 'workcalendar' && <WorkCalendar />}
        {route === 'assistant' && <AssistantChatPage />}
        {route === 'scenarios' && <p>Scenarios (placeholder)</p>}
      </div>

      {/* 浮動聊天窗口 - 在非助理頁面顯示 */}
      {route !== 'assistant' && <FloatingChat />}

      {/* footer removed per design */}
    </div>
  )
}
