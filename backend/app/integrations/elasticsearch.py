from typing import Any, Dict, Optional, Tuple

import httpx

from app.config import ES_PASS, ES_URL, ES_USER


_es_client: Optional[httpx.AsyncClient] = None


def _get_auth() -> Optional[Tuple[str, str]]:
    if ES_USER and ES_PASS:
        return ES_USER, ES_PASS
    return None


async def _get_client() -> httpx.AsyncClient:
    global _es_client

    if _es_client is None or _es_client.is_closed:
        _es_client = httpx.AsyncClient(
            base_url=ES_URL,
            auth=_get_auth(),
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(60.0),
        )

    return _es_client


async def close_es_client() -> None:
    global _es_client

    if _es_client is not None and not _es_client.is_closed:
        await _es_client.aclose()

    _es_client = None


async def es_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    client = await _get_client()

    response = await client.post(
        f"/{path.lstrip('/')}",
        json=body,
    )

    response.raise_for_status()
    return response.json()


async def es_get(path: str) -> Dict[str, Any]:
    client = await _get_client()

    response = await client.get(f"/{path.lstrip('/')}")

    response.raise_for_status()
    return response.json()