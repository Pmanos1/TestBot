# app/main.py

import os
import asyncio
import aiofiles

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from app.pubsub import broadcast
from app.kclivefeed import run_ws
from app.kc import router as kc_router
from app.algoapis import router as algo_router
from app.config import settings, Settings
from app.logger_config import logger

# ← Import your DB setup
from app.db import init_db

app = FastAPI(title=settings.PROJECT_TITLE)

# Include your routers
app.include_router(kc_router)
app.include_router(algo_router)

# ─── Static files & templates ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "..", "templates"))
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "..", "static")),
    name="static"
)

# ─── Initialize DB and broadcaster on startup ───────────────────────────────
@app.on_event("startup")
async def startup_event():
    # 1) Create tables if they don't exist
    init_db()
    # 2) Connect your broadcaster
    await broadcast.connect()

# ─── Disconnect broadcaster on shutdown ─────────────────────────────────────
@app.on_event("shutdown")
async def shutdown_event():
    await broadcast.disconnect()

# ─── Feed task management ──────────────────────────────────────────────────
FEED_TASKS: dict[str, asyncio.Task]   = {}
STOP_EVENTS: dict[str, asyncio.Event] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    config_dict = {}
    for key in dir(settings):
        if key.startswith("__") or callable(getattr(settings, key)):
            continue
        value = getattr(settings, key)
        if any(s in key.upper() for s in ["SECRET", "PASSPHRASE", "KEY", "TOKEN"]):
            config_dict[key] = mask_value(value)
        else:
            config_dict[key] = value

    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request,
            "default_pair": settings.DEFAULT_PAIR,
            "config": config_dict
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok"}

def mask_value(value: str) -> str:
    if not isinstance(value, str):
        return value
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"

@app.get("/config")
def get_config():
    config_dict = {}
    for key in dir(Settings):
        # Skip private attributes and methods
        if key.startswith("__") or callable(getattr(Settings, key)):
            continue

        value = getattr(Settings, key)

        if any(s in key.upper() for s in ["SECRET", "PASSPHRASE", "KEY", "TOKEN"]):
            config_dict[key] = mask_value(value)
        else:
            config_dict[key] = value
    return config_dict

@app.post("/start/{pair}")
async def start_feed(pair: str):
    if pair in FEED_TASKS and not FEED_TASKS[pair].done():
        return JSONResponse(
            {"error": f"feed for {pair} already running"},
            status_code=400
        )

    stop_evt = asyncio.Event()
    STOP_EVENTS[pair] = stop_evt
    FEED_TASKS[pair] = asyncio.create_task(run_ws(pair, stop_evt))

    logger.info("[main] | 🚀 Started feed for %s", pair)
    return {"status": "running", "pair": pair}

@app.post("/stop/{pair}")
async def stop_feed_pair(pair: str):
    if pair not in FEED_TASKS:
        return JSONResponse(
            {"error": f"no feed running for {pair}"},
            status_code=404
        )

    STOP_EVENTS[pair].set()
    try:
        await asyncio.wait_for(FEED_TASKS[pair], timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("[main] | ✋ Feed task for %s hung, cancelling", pair)
        FEED_TASKS[pair].cancel()

    del FEED_TASKS[pair]
    del STOP_EVENTS[pair]

    logger.info("[main] | 🛑 Stopped feed for %s", pair)
    return {"status": "stopped", "pair": pair}

@app.post("/stop")
async def stop_all():
    for evt in STOP_EVENTS.values():
        evt.set()
    await asyncio.gather(*FEED_TASKS.values(), return_exceptions=True)
    FEED_TASKS.clear()
    STOP_EVENTS.clear()
    logger.info("[main] | 🧹 Stopped all feeds")
    return {"status": "stopped_all"}

# ─── WebSocket endpoint ────────────────────────────────────────────────────
@app.websocket("/ws/{pair}")
async def ws_endpoint(ws: WebSocket, pair: str):
    await ws.accept()
    channel = f"price_feed:{pair}"

    async with broadcast.subscribe(channel=channel) as subscriber:
        try:
            async for event in subscriber:
                await ws.send_text(event.message)
        except WebSocketDisconnect:
            logger.info("[ws] | 📴 Client disconnected for %s", pair)
        except Exception as err:
            logger.error("[ws] | ⚠️ Unexpected error for %s: %s", pair, err)

# ─── Log‐streaming & status endpoints ────────────────────────────────────────
def find_log_path(logger) -> str:
    for h in logger.handlers:
        if hasattr(h, "baseFilename"):
            return h.baseFilename
    raise RuntimeError("No FileHandler attached to logger")

async def log_event_generator(request: Request, log_file: str):
    async with aiofiles.open(log_file, mode="r") as f:
        await f.seek(0, os.SEEK_END)
        while True:
            if await request.is_disconnected():
                break
            line = await f.readline()
            if not line:
                await asyncio.sleep(0.2)
                continue
            yield {"data": line.rstrip()}

@app.get("/logs")
async def logs(request: Request):
    log_file = find_log_path(logger)
    return EventSourceResponse(log_event_generator(request, log_file))

@app.get("/feed/status/{pair}")
async def feed_status(pair: str):
    running = pair in FEED_TASKS and not FEED_TASKS[pair].done()
    return {"running": running}
