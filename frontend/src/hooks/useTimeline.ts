import { useState, useCallback, useMemo } from 'react'

// Timeline constants
const T0_HOUR = 8  // Start time: 08:00
const T1_HOUR = 32 // End time: next day 08:00 (24 hours from 08:00)
const BASE_HOUR_WIDTH = 120 // Base width in pixels for 1 hour at zoom=1 (increased for better precision)

export interface TimelineConfig {
  zoom: number
  setZoom: (zoom: number) => void
  timeToX: (timeInHours: number) => number
  durationToWidth: (durationInHours: number) => number
  xToTime: (x: number) => number
  snapToGrid: (timeInHours: number) => number
  getSnapInterval: () => number
  t0: number
  t1: number
  totalWidth: number
  getTimeMarks: () => TimeMark[]
}

export interface TimeMark {
  time: number // Time in hours (e.g., 8.5 for 08:30)
  x: number    // X position in pixels
  label: string
  type: 'major' | 'minor' // Major = show label, Minor = just line
}

export function useTimeline(): TimelineConfig {
  const [zoom, setZoom] = useState(1)
  
  // Convert time (in hours) to X position in pixels
  const timeToX = useCallback((timeInHours: number): number => {
    return (timeInHours - T0_HOUR) * BASE_HOUR_WIDTH * zoom
  }, [zoom])
  
  // Convert duration (in hours) to width in pixels
  const durationToWidth = useCallback((durationInHours: number): number => {
    return durationInHours * BASE_HOUR_WIDTH * zoom
  }, [zoom])
  
  // Convert X position back to time (for drag operations)
  const xToTime = useCallback((x: number): number => {
    return (x / (BASE_HOUR_WIDTH * zoom)) + T0_HOUR
  }, [zoom])
  
  // Total timeline width
  const totalWidth = useMemo(() => {
    return (T1_HOUR - T0_HOUR) * BASE_HOUR_WIDTH * zoom
  }, [zoom])
  
  // Get snap interval based on zoom level
  const getSnapInterval = useCallback((): number => {
    if (zoom <= 1.5) return 1 // 1 hour
    if (zoom <= 3) return 0.5 // 30 minutes
    return 1/6 // 10 minutes (max precision)
  }, [zoom])
  
  // Snap time to nearest grid interval
  const snapToGrid = useCallback((timeInHours: number): number => {
    const interval = getSnapInterval()
    return Math.round(timeInHours / interval) * interval
  }, [getSnapInterval])
  
  // Generate time marks based on zoom level
  const getTimeMarks = useCallback((): TimeMark[] => {
    const marks: TimeMark[] = []
    
    // Determine granularity based on zoom
    if (zoom <= 1.5) {
      // Overview: 1 hour intervals
      for (let h = T0_HOUR; h < T1_HOUR; h++) {
        const displayHour = h % 24 // 將小時轉換為 0-23 範圍
        marks.push({
          time: h,
          x: timeToX(h),
          label: `${String(displayHour).padStart(2, '0')}:00`,
          type: 'major'
        })
      }
    } else if (zoom <= 3) {
      // Medium: 30 minute intervals
      for (let h = T0_HOUR; h < T1_HOUR; h++) {
        const displayHour = h % 24
        marks.push({
          time: h,
          x: timeToX(h),
          label: `${String(displayHour).padStart(2, '0')}:00`,
          type: 'major'
        })
        if (h < T1_HOUR) {
          marks.push({
            time: h + 0.5,
            x: timeToX(h + 0.5),
            label: `${String(displayHour).padStart(2, '0')}:30`,
            type: 'minor'
          })
        }
      }
    } else {
      // Detail: 10 minute intervals (max precision)
      for (let h = T0_HOUR; h < T1_HOUR; h++) {
        const displayHour = h % 24
        for (let m = 0; m < 60; m += 10) {
          const time = h + m / 60
          if (time >= T1_HOUR) break
          
          marks.push({
            time,
            x: timeToX(time),
            label: m === 0 ? `${String(displayHour).padStart(2, '0')}:00` : `${String(displayHour).padStart(2, '0')}:${String(m).padStart(2, '0')}`,
            type: m === 0 ? 'major' : 'minor'
          })
        }
      }
    }
    
    return marks
  }, [zoom, timeToX])
  
  return {
    zoom,
    setZoom,
    timeToX,
    durationToWidth,
    xToTime,
    snapToGrid,
    getSnapInterval,
    t0: T0_HOUR,
    t1: T1_HOUR,
    totalWidth,
    getTimeMarks
  }
}
