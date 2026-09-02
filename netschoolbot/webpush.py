import json
import os
from pathlib import Path

try:
    from pywebpush import webpush, WebPushException
except Exception:  # pragma: no cover - optional dependency during local editing
    webpush = None
    WebPushException = Exception


from .config import NETSCHOOL_USERS_DIR, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_SUBJECT

PUSH_STORE_FILE = NETSCHOOL_USERS_DIR / "webpush_subscriptions.json"


def _load_store() -> dict:
    if not PUSH_STORE_FILE.exists():
        return {"users": {}}
    try:
        data = json.loads(PUSH_STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("users"), dict):
            return data
    except Exception:
        pass
    return {"users": {}}


def _save_store(store: dict) -> None:
    PUSH_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUSH_STORE_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def _vapid_public_key() -> str:
    return VAPID_PUBLIC_KEY


def _vapid_private_key() -> str:
    return VAPID_PRIVATE_KEY


def _vapid_subject() -> str:
    return VAPID_SUBJECT


def push_available() -> bool:
    return bool(webpush and _vapid_public_key() and _vapid_private_key())


def vapid_public_key() -> str:
    return _vapid_public_key()


def normalize_subscription(subscription: dict) -> dict | None:
    if not isinstance(subscription, dict):
        return None
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        return None
    return {
        "endpoint": endpoint,
        "keys": {
            "p256dh": p256dh,
            "auth": auth,
        },
    }


def get_user_subscriptions(user_id: int) -> list[dict]:
    store = _load_store()
    users = store.get("users", {})
    items = users.get(str(int(user_id))) or []
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        normalized = normalize_subscription(item)
        if normalized:
            normalized.update({
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "user_agent": item.get("user_agent"),
            })
            result.append(normalized)
    return result


def upsert_user_subscription(user_id: int, subscription: dict, user_agent: str = "") -> dict:
    normalized = normalize_subscription(subscription)
    if not normalized:
        raise ValueError("Некорректная push-подписка")
    store = _load_store()
    users = store.setdefault("users", {})
    key = str(int(user_id))
    items = list(users.get(key) or [])
    now = __import__("datetime").datetime.now().isoformat()
    updated = False
    for item in items:
        if item.get("endpoint") == normalized["endpoint"]:
            item.update(normalized)
            item["updated_at"] = now
            if user_agent:
                item["user_agent"] = user_agent[:300]
            updated = True
            break
    if not updated:
        payload = dict(normalized)
        payload["created_at"] = now
        payload["updated_at"] = now
        if user_agent:
            payload["user_agent"] = user_agent[:300]
        items.append(payload)
    users[key] = items
    _save_store(store)
    return {"count": len(items)}


def remove_user_subscription(user_id: int, endpoint: str | None = None) -> dict:
    store = _load_store()
    users = store.setdefault("users", {})
    key = str(int(user_id))
    items = list(users.get(key) or [])
    if endpoint:
        items = [item for item in items if item.get("endpoint") != endpoint]
    else:
        items = []
    if items:
        users[key] = items
    else:
        users.pop(key, None)
    _save_store(store)
    return {"count": len(items)}


def push_summary(user_id: int) -> dict:
    subscriptions = get_user_subscriptions(user_id)
    return {
        "configured": push_available(),
        "count": len(subscriptions),
        "public_key": vapid_public_key(),
    }


def send_user_push(user_id: int, title: str, body: str, url: str, tag: str = "netschool", data: dict | None = None, icon: str | None = None) -> dict:
    if not push_available():
        return {"ok": False, "reason": "push_not_configured", "sent": 0, "removed": 0}
    subscriptions = get_user_subscriptions(user_id)
    if not subscriptions:
        return {"ok": False, "reason": "no_subscriptions", "sent": 0, "removed": 0}

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
        "icon": icon or "/mini/netschool/icon.svg",
        "badge": icon or "/mini/netschool/icon.svg",
        "data": data or {},
    }, ensure_ascii=False)
    vapid_claims = {"sub": _vapid_subject()}
    invalid_endpoints = []
    sent = 0

    for item in subscriptions:
        subscription_info = {
            "endpoint": item["endpoint"],
            "keys": item["keys"],
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=_vapid_private_key(),
                vapid_claims=vapid_claims,
                ttl=120,
            )
            sent += 1
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in {404, 410}:
                invalid_endpoints.append(item["endpoint"])
        except Exception:
            continue

    if invalid_endpoints:
        store = _load_store()
        users = store.setdefault("users", {})
        key = str(int(user_id))
        current = list(users.get(key) or [])
        users[key] = [item for item in current if item.get("endpoint") not in invalid_endpoints]
        if not users[key]:
            users.pop(key, None)
        _save_store(store)

    return {
        "ok": sent > 0,
        "reason": "sent" if sent > 0 else "delivery_failed",
        "sent": sent,
        "removed": len(invalid_endpoints),
    }