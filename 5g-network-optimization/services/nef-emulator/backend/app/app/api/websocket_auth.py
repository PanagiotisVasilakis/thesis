from fastapi import WebSocket


async def require_websocket_user(websocket: WebSocket) -> bool:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return False

    from app.api import deps
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        deps.get_current_user(db=db, token=token)
        return True
    except Exception:
        await websocket.close(code=1008)
        return False
    finally:
        db.close()
