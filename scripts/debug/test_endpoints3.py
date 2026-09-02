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
    
    # Try fetching term marks. SGO api for term grades is usually 'student/diary/termMarks'
    # BUT wait, the base URL in netschoolpy might be different if it's 'student/diary...' vs 'reports/...'
    eps = [
        "student/termmarks",
        "student/diary/termmarks",
        "student/marks/term",
        "reports/student/totals",
        "reports/student/terms",
        "student/diary/totals",
        "student/diary/finals",
        "student/periodmarks",
        "student/diary/termMarksForSubject",
        "student/diary/periodmarks"
    ]
    for ep in eps:
        try:
            resp = await client._authed_get(ep, params={"studentId": client._student_id})
            if resp.status_code == 200:
                print(f"FOUND 200 on {ep}")
                # print first few keys
                print("KEYS:", list(resp.json().keys())[:5])
        except BaseException as e:
            pass
            
    await client.close()

_run_async(test())
