import React, { useEffect, useState } from 'react'
import { api } from '../api/api'
import './WorkCalendar.css'

interface WorkCalendarDay {
  work_date: string
  work_hours: number
  start_time: string
  note?: string
}

export default function WorkCalendar() {
  const [currentYear, setCurrentYear] = useState(new Date().getFullYear())
  const [currentMonth, setCurrentMonth] = useState(new Date().getMonth() + 1)
  const [calendarDays, setCalendarDays] = useState<Map<string, WorkCalendarDay>>(new Map())
  const [loading, setLoading] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadCalendar()
  }, [currentYear, currentMonth])

  async function loadCalendar() {
    setLoading(true)
    setHasChanges(false)
    try {
      const data = await api.getWorkCalendar(currentYear, currentMonth)
      console.log('📅 載入日曆資料:', data)
      console.log('📅 資料筆數:', data.length)
      const map = new Map<string, WorkCalendarDay>()
      data.forEach((day: WorkCalendarDay) => {
        console.log(`  ${day.work_date}: ${day.work_hours} 小時`)
        map.set(day.work_date, day)
      })
      setCalendarDays(map)
    } catch (error) {
      console.error('Failed to load calendar:', error)
    } finally {
      setLoading(false)
    }
  }

  function getDaysInMonth(year: number, month: number): Date[] {
    const firstDay = new Date(year, month - 1, 1)
    const lastDay = new Date(year, month, 0)
    const days: Date[] = []
    
    for (let d = 1; d <= lastDay.getDate(); d++) {
      days.push(new Date(year, month - 1, d))
    }
    
    return days
  }

  function formatDate(date: Date): string {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  function getWeekdayName(date: Date): string {
    const weekdays = ['日', '一', '二', '三', '四', '五', '六']
    return weekdays[date.getDay()]
  }

  function isWeekend(date: Date): boolean {
    const day = date.getDay()
    return day === 0 || day === 6
  }

  function handleHoursChange(dateStr: string, hours: number) {
    const data = {
      work_date: dateStr,
      work_hours: hours,
      start_time: '08:00'
    }
    
    // 只更新本地狀態
    const newMap = new Map(calendarDays)
    newMap.set(dateStr, data as WorkCalendarDay)
    setCalendarDays(newMap)
    setHasChanges(true)
  }

  async function handleSave() {
    if (!hasChanges) return
    
    setSaving(true)
    try {
      // 準備整個月份的所有日期資料
      const allDays = getDaysInMonth(currentYear, currentMonth)
      const daysToSave = allDays.map(date => {
        const dateStr = formatDate(date)
        const existingData = calendarDays.get(dateStr)
        
        // 如果有現有資料就用現有的，否則用預設值
        return {
          work_date: dateStr,
          work_hours: existingData?.work_hours ?? (isWeekend(date) ? 0 : 16),
          start_time: existingData?.start_time ?? '08:00',
          note: existingData?.note ?? ''
        }
      })
      
      console.log('💾 準備儲存資料:', daysToSave.length, '筆')
      console.log('💾 前5筆範例:', daysToSave.slice(0, 5))
      
      await api.batchUpsertWorkCalendar({
        days: daysToSave
      })
      
      console.log('✅ 儲存成功')
      setHasChanges(false)
      alert('儲存成功！')
    } catch (error) {
      console.error('Failed to save calendar:', error)
      alert('儲存失敗')
    } finally {
      setSaving(false)
    }
  }

  function goToPrevMonth() {
    if (currentMonth === 1) {
      setCurrentYear(currentYear - 1)
      setCurrentMonth(12)
    } else {
      setCurrentMonth(currentMonth - 1)
    }
  }

  function goToNextMonth() {
    if (currentMonth === 12) {
      setCurrentYear(currentYear + 1)
      setCurrentMonth(1)
    } else {
      setCurrentMonth(currentMonth + 1)
    }
  }

  const days = getDaysInMonth(currentYear, currentMonth)

  return (
    <div className="work-calendar-container">
      <div className="calendar-header">
        <h1>生產時數管理</h1>
        <div className="calendar-header-actions">
          <div className="month-navigator">
            <button onClick={goToPrevMonth}>◀ 上個月</button>
            <span className="current-month">
              {currentYear} 年 {currentMonth} 月
            </span>
            <button onClick={goToNextMonth}>下個月 ▶</button>
          </div>
          <button 
            onClick={handleSave} 
            disabled={!hasChanges || saving}
            className="save-btn"
          >
            {saving ? '儲存中...' : hasChanges ? '💾 儲存變更' : '✓ 已儲存'}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="loading">載入中...</div>
      ) : (
        <div className="calendar-grid">
          <div className="calendar-weekdays">
            <div className="weekday-header">日</div>
            <div className="weekday-header">一</div>
            <div className="weekday-header">二</div>
            <div className="weekday-header">三</div>
            <div className="weekday-header">四</div>
            <div className="weekday-header">五</div>
            <div className="weekday-header">六</div>
          </div>

          <div className="calendar-days">
            {/* 填充第一週的空白 */}
            {Array.from({ length: days[0].getDay() }).map((_, i) => (
              <div key={`empty-${i}`} className="calendar-day empty"></div>
            ))}

            {/* 渲染每一天 */}
            {days.map((date) => {
              const dateStr = formatDate(date)
              const dayData = calendarDays.get(dateStr)
              const workHours = dayData?.work_hours ?? (isWeekend(date) ? 0 : 16)
              const isWeekendDay = isWeekend(date)

              return (
                <div
                  key={dateStr}
                  className={`calendar-day ${isWeekendDay ? 'weekend' : ''}`}
                >
                  <div className="day-header">
                    <span className="day-number">{date.getDate()}</span>
                    <span className="day-weekday">({getWeekdayName(date)})</span>
                  </div>
                  <div className="day-content">
                    <input
                      type="number"
                      min="0"
                      max="24"
                      step="0.5"
                      value={workHours}
                      onChange={(e) => {
                        const value = parseFloat(e.target.value)
                        if (value >= 0 && value <= 24) {
                          handleHoursChange(dateStr, value)
                        }
                      }}
                      className="hours-input"
                    />
                    <span className="hours-label">小時</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
