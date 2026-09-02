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
    
    eps = [
        ("student/diary/termMarks", {"studentId": client._student_id}),
        ("student/diary/termMarks", {"studentId": client._student_id, "schoolYearId": client._year_id}),
        ("student/diary/termMarks", {"studentId": client._student_id, "yearId": client._year_id})
    ]
    for ep, params in eps:
        try:
            resp = await client._authed_get(ep, params=params)
            if resp.status_code == 200:
                print(f"FOUND 200 on {ep} with {params}")
                # print first few keys
                print("KEYS:", list(resp.json().keys()))
                break
            else:
                print(f"Failed {ep} ({resp.status_code})")
        except Exception as e:
            print(f"EXC {ep}: {e}")
            
    await client.close()

_run_async(test())
