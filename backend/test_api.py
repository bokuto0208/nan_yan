import requests

try:
    response = requests.get('http://localhost:8000/api/scheduling/schedules?date=2025-12-25')
    data = response.json()
    
    schedules = data.get('schedules', [])
    print(f"API 回傳 {len(schedules)} 個區塊\n")
    
    if len(schedules) > 0:
        print("前5個:")
        for s in schedules[:5]:
            print(f"  {s['id']}: {s['productId']} @ {s['machineId']} ({s['scheduledDate']})")
            print(f"    startHour={s['startHour']:.2f}, isSplit={s.get('isSplit')}, splitPart={s.get('splitPart')}/{s.get('totalSplits')}")
    else:
        print("沒有資料！")
        
except Exception as e:
    print(f"錯誤: {e}")
    print("請確認後端是否正在運行")
