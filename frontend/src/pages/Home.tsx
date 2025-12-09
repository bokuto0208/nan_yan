import React from 'react'

type MachineData = {
  id: number
  orderId: string
  productId: string
  status: 'running' | 'idle' | 'maintenance'
  progress: number
  currentQty: number
  totalQty: number
}

export default function Home() {
  const machines: MachineData[] = [
    { id: 1, orderId: 'ORD-2024-001', productId: 'P-500A', status: 'running', progress: 65, currentQty: 325, totalQty: 500 },
    { id: 2, orderId: 'ORD-2024-002', productId: 'P-200B', status: 'idle', progress: 0, currentQty: 0, totalQty: 300 },
    { id: 3, orderId: 'ORD-2024-003', productId: 'P-800C', status: 'maintenance', progress: 45, currentQty: 360, totalQty: 800 },
    { id: 4, orderId: 'ORD-2024-004', productId: 'P-100D', status: 'running', progress: 99, currentQty: 99, totalQty: 100 }
  ]

  const getStatusLabel = (status: string) => {
    const labels = { running: '運行中', idle: '待命', maintenance: '維護中' }
    return labels[status as keyof typeof labels] || status
  }

  return (
    <div className="page home-page">
      <div className="machines-grid">
        {machines.map((m) => (
          <div key={m.id} className="machine-column">
            <div className="machine-card">
              <div className="machine-card-content">
                {/* Left: Order & Product Info */}
                <div className="machine-card-info">
                  <div>
                    <div className="machine-card-info-label">工單編號</div>
                    <div className="machine-card-info-value">{m.orderId}</div>
                  </div>
                  <div>
                    <div className="machine-card-info-label">產品</div>
                    <div className="machine-card-info-value">{m.productId}</div>
                  </div>
                  <div>
                    <div className="machine-card-info-label">生產進度</div>
                    <div className="machine-card-info-value" style={{ color: '#1ea0e9', fontWeight: 700, fontSize: '16px' }}>
                      {m.currentQty} / {m.totalQty} pcs
                    </div>
                  </div>
                  {/* Progress bar at bottom of left section */}
                  <div className="progress" style={{ marginTop: '8px' }}>
                    <div
                      className={`progress-fill ${m.progress > 100 ? 'over' : ''}`}
                      style={{ width: `${m.progress > 100 ? 100 : m.progress}%`, '--progress-width': `${m.progress}%` } as React.CSSProperties}
                    />
                    <span className="progress-text">{m.progress}%</span>
                  </div>
                </div>

                {/* Right: Status Badge */}
                <div className="machine-status-badge">
                  <span className={`status-badge ${m.status}`}>{getStatusLabel(m.status)}</span>
                </div>
              </div>
            </div>
            <div className="machine-label">機台 {m.id}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
