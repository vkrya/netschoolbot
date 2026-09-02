import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from netschoolbot.web.miniapp import _get_netschool_miniapp_user, _login_netschool_client, _run_async
import json

async def test():
    with open(Path(__file__).resolve().parents[2] / "data" / "netschool_users" / "netschool_users.json", "r") as f:
        data = json.load(f)
    if not data.get("users"): return
    user_id = list(data["users"].keys())[0]
    user_data = data["users"][user_id]
    
    client = await _login_netschool_client(int(user_id), user_data)
    from datetime import date, timedelta
    
    today = date.today()
    for w in range(2):
        start = today - timedelta(days=today.weekday() + 7 * w)
        end = start + timedelta(days=5)
        resp = await client._authed_get("student/diary", params={
            "studentId": client._student_id,
            "yearId": client._year_id,
            "weekStart": start.isoformat(),
            "weekEnd": end.isoformat(),
        })
        raw_data = resp.json()
        
        for day in raw_data.get("weekDays", []):
            for lesson in day.get("lessons", []):
                for assign in lesson.get("assignments", []):
                    # check mark
                    mark = assign.get("mark")
                    # print typeId and if we have a mark
                    if mark:
                        print("MARK:", assign.get("typeId"), type(mark), assign.get("classMeetingId"))
                    
    await client.close()

_run_async(test())
