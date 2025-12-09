import { MachineProductHistory } from '../utils/schedulingAlgorithms'

/**
 * 模擬的機台-產品歷史數據
 * 實際應用中，這些數據應該從後端數據庫獲取
 */
export const mockMachineProductHistory: MachineProductHistory[] = [
  // 產品 P001 在各機台的表現
  {
    machineId: 1,
    productCode: 'P001',
    totalProduced: 5000,
    averageYieldRate: 0.95, // 95% 良率
    averageProductionTime: 3.5,
    productionCount: 25
  },
  {
    machineId: 2,
    productCode: 'P001',
    totalProduced: 3000,
    averageYieldRate: 0.92,
    averageProductionTime: 3.8,
    productionCount: 15
  },
  {
    machineId: 3,
    productCode: 'P001',
    totalProduced: 4500,
    averageYieldRate: 0.98, // 最佳良率
    averageProductionTime: 3.2, // 最短時間
    productionCount: 30 // 最常使用
  },
  {
    machineId: 4,
    productCode: 'P001',
    totalProduced: 2000,
    averageYieldRate: 0.90,
    averageProductionTime: 4.0,
    productionCount: 10
  },
  
  // 產品 P002 在各機台的表現
  {
    machineId: 1,
    productCode: 'P002',
    totalProduced: 3500,
    averageYieldRate: 0.88,
    averageProductionTime: 2.5,
    productionCount: 20
  },
  {
    machineId: 2,
    productCode: 'P002',
    totalProduced: 6000,
    averageYieldRate: 0.96, // 最佳良率
    averageProductionTime: 2.2, // 最短時間
    productionCount: 35 // 最常使用
  },
  {
    machineId: 3,
    productCode: 'P002',
    totalProduced: 2500,
    averageYieldRate: 0.91,
    averageProductionTime: 2.8,
    productionCount: 15
  },
  {
    machineId: 4,
    productCode: 'P002',
    totalProduced: 4000,
    averageYieldRate: 0.93,
    averageProductionTime: 2.4,
    productionCount: 25
  },
  
  // 產品 P003 在各機台的表現
  {
    machineId: 1,
    productCode: 'P003',
    totalProduced: 4000,
    averageYieldRate: 0.94,
    averageProductionTime: 4.5,
    productionCount: 18
  },
  {
    machineId: 2,
    productCode: 'P003',
    totalProduced: 3000,
    averageYieldRate: 0.89,
    averageProductionTime: 5.0,
    productionCount: 12
  },
  {
    machineId: 3,
    productCode: 'P003',
    totalProduced: 2000,
    averageYieldRate: 0.92,
    averageProductionTime: 4.8,
    productionCount: 10
  },
  {
    machineId: 4,
    productCode: 'P003',
    totalProduced: 5500,
    averageYieldRate: 0.97, // 最佳良率
    averageProductionTime: 4.2, // 最短時間
    productionCount: 28 // 最常使用
  },
  
  // 產品 P004 在各機台的表現
  {
    machineId: 1,
    productCode: 'P004',
    totalProduced: 7000,
    averageYieldRate: 0.96,
    averageProductionTime: 3.0,
    productionCount: 40 // 最常使用
  },
  {
    machineId: 2,
    productCode: 'P004',
    totalProduced: 4500,
    averageYieldRate: 0.93,
    averageProductionTime: 3.3,
    productionCount: 25
  },
  {
    machineId: 3,
    productCode: 'P004',
    totalProduced: 5000,
    averageYieldRate: 0.98, // 最佳良率
    averageProductionTime: 2.8, // 最短時間
    productionCount: 30
  },
  {
    machineId: 4,
    productCode: 'P004',
    totalProduced: 3500,
    averageYieldRate: 0.91,
    averageProductionTime: 3.5,
    productionCount: 20
  },
  
  // 產品 P005 在各機台的表現
  {
    machineId: 1,
    productCode: 'P005',
    totalProduced: 2500,
    averageYieldRate: 0.90,
    averageProductionTime: 5.5,
    productionCount: 12
  },
  {
    machineId: 2,
    productCode: 'P005',
    totalProduced: 5500,
    averageYieldRate: 0.95,
    averageProductionTime: 5.0,
    productionCount: 28 // 最常使用
  },
  {
    machineId: 3,
    productCode: 'P005',
    totalProduced: 4000,
    averageYieldRate: 0.97, // 最佳良率
    averageProductionTime: 4.8, // 最短時間
    productionCount: 22
  },
  {
    machineId: 4,
    productCode: 'P005',
    totalProduced: 3000,
    averageYieldRate: 0.92,
    averageProductionTime: 5.2,
    productionCount: 16
  }
]

/**
 * 根據產品代碼和策略獲取推薦機台
 */
export function getRecommendedMachine(
  productCode: string,
  strategy: 'quality' | 'time' | 'frequency'
): { machineId: number; reason: string } | null {
  const productHistory = mockMachineProductHistory.filter(h => h.productCode === productCode)
  
  if (productHistory.length === 0) {
    return null
  }
  
  let best: MachineProductHistory
  let reason: string
  
  switch (strategy) {
    case 'quality':
      best = productHistory.reduce((a, b) => a.averageYieldRate > b.averageYieldRate ? a : b)
      reason = `良率最佳 ${(best.averageYieldRate * 100).toFixed(1)}%`
      break
    case 'time':
      best = productHistory.reduce((a, b) => a.averageProductionTime < b.averageProductionTime ? a : b)
      reason = `生產時間最短 ${best.averageProductionTime.toFixed(1)}h`
      break
    case 'frequency':
      best = productHistory.reduce((a, b) => a.productionCount > b.productionCount ? a : b)
      reason = `最常使用 ${best.productionCount}次`
      break
    default:
      return null
  }
  
  return {
    machineId: best.machineId,
    reason
  }
}
