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
    
    client = await _login_netschool_client(int(user_id), data["users"][user_id])
    print("student", client._student_id)
    
    eps = [
        "student/termMarks",
        "student/diary/termMarks",
        "student/diary/term-marks",
        "student/period/marks",
        "student/diary/periodmarks",
        "mobile/v1/student/marks",
        "mobile/v1/student/totals",
        "student/totals",
        "student/diary/totals",
        "reports/student/totals",
        "student/diary/period",
        "reports/student/marks",
    ]
    for ep in eps:
        try:
            resp = await client._authed_get(ep, params={"studentId": client._student_id})
            if resp.status_code == 200:
                print(f"BINGO {ep}:", resp.json())
                break
        except Exception as e:
            pass
            
    await client.close()

_run_async(test())
