import time
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport
from fastapi.responses import JSONResponse
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)

class MemoryRedis:
    """Minimal in-memory stand-in for redis required by FastAPILimiter."""

    def __init__(self):
        self._data = {}

    async def script_load(self, script: str) -> str:
        return "sha"

    async def evalsha(self, sha: str, _keys: int, key: str, limit: str, expire_ms: str):
        limit = int(limit)
        expire_ms = int(expire_ms)
        now = int(time.time() * 1000)
        count, exp = self._data.get(key, (0, now + expire_ms))
        if now > exp:
            count = 0
            exp = now + expire_ms
        if count >= limit:
            return max(exp - now, 0)
        count += 1
        self._data[key] = (count, exp)
        return 0

    async def close(self) -> None:
        pass


def _create_client() -> TestClient:
    app = FastAPI()

    @app.on_event("startup")
    async def startup() -> None:
        await FastAPILimiter.init(MemoryRedis())

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": "HTTPException", "message": exc.detail})

    @app.exception_handler(Exception)
    async def generic_exc(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": type(exc).__name__, "message": str(exc)})

    @app.get("/limited", dependencies=[Depends(RateLimiter(times=1, seconds=1))])
    async def limited():
        return {"ok": True}

    @app.get("/err")
    async def err():
        raise HTTPException(status_code=400, detail="boom")

    @app.get("/crash")
    async def crash():
        raise ValueError("bad")

    client = TestClient(transport=ASGITransport(app=app), raise_server_exceptions=False)
    client.__enter__()
    return client


def test_rate_limit_triggered() -> None:
    client = _create_client()
    assert client.get("/limited").status_code == 200
    resp = client.get("/limited")
    assert resp.status_code == 429
    assert resp.json() == {"error": "HTTPException", "message": "Too Many Requests"}
    client.__exit__(None, None, None)


def test_http_exception_format() -> None:
    client = _create_client()
    resp = client.get("/err")
    assert resp.status_code == 400
    assert resp.json() == {"error": "HTTPException", "message": "boom"}
    client.__exit__(None, None, None)


def test_unhandled_exception_format() -> None:
    client = _create_client()
    resp = client.get("/crash")
    assert resp.status_code == 500
    assert resp.json() == {"error": "ValueError", "message": "bad"}
    client.__exit__(None, None, None)
