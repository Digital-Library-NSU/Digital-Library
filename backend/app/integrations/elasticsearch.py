from typing import Any, Dict

import requests

from app.config import ES_PASS, ES_URL, ES_USER


session = requests.Session()
if ES_USER and ES_PASS:
    session.auth = (ES_USER, ES_PASS)
session.headers.update({"Content-Type": "application/json"})


_pg_conn = None


def es_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    r = session.post(f"{ES_URL}/{path.lstrip('/')}", json=body, timeout=60)
    if r.status_code >= 400:
        r.raise_for_status()
    return r.json()


def es_get(path: str) -> Dict[str, Any]:
    r = session.get(f"{ES_URL}/{path.lstrip('/')}", timeout=30)
    if r.status_code >= 400:
        r.raise_for_status()
    return r.json()
