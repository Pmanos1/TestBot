# app/algoapis.py

import asyncio
from contextlib import suppress
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

import app.algo as algo
from app.algo import run_algo, SYMBOL
from app.logger_config import logger

# DB imports
from app.db import get_db, list_trades_by_symbol

router = APIRouter(prefix="/algo", tags=["algo"])
_algo_task: asyncio.Task | None = None


def _save_trades():
    """
    Export all SELL trades from the DB into live_trades.csv,
    including their PnL and timestamp.
    """
    with get_db() as db:
        trades = list_trades_by_symbol(db, SYMBOL, skip=0, limit=10_000)

    # Only include sells in the CSV, with the fields your UI expects
    rows = []
    for t in trades:
        if t.type.lower() == "sell":
            rows.append({
                "Sell Price": t.price,
                "Sell Time":  t.timestamp.isoformat(),
                "PnL":         t.pnl or 0.0,
            })

    df = pd.DataFrame(rows)
    df.to_csv("live_trades.csv", index=False)
    logger.info("[algo] | Saved %d trades to live_trades.csv", len(df))


@router.post("/start")
async def start_algo():
    logger.info("[algo] | POST /algo/start called")
    global _algo_task

    if not algo.models_ready:
        logger.warning("[algo] | Models not ready; cannot start")
        raise HTTPException(503, "Prediction models not loaded; cannot start algorithm")

    if _algo_task and not _algo_task.done():
        logger.warning("[algo] | Algorithm already running")
        raise HTTPException(400, "Algorithm already running")

    # reset sell-only flag
    algo.stop_requested = False

    # start the trading loop
    _algo_task = asyncio.create_task(run_algo())
    logger.info("[algo] | Algorithm task started")
    return {"status": "started"}


@router.post("/stop")
async def stop_algo():
    logger.info("[algo] | POST /algo/stop called — entering sell-only mode")
    global _algo_task

    if not _algo_task or _algo_task.done():
        logger.warning("[algo] | Stop requested but algorithm not running")
        raise HTTPException(400, "Algorithm not running")

    algo.stop_requested = True
    return {"status": "stopping"}


@router.get("/status")
async def algo_status():
    logger.info("[algo] | GET /algo/status called")

    # 1) Is the algo task still running?
    running = bool(_algo_task and not _algo_task.done())

    # 2) Recompute stats from the DB
    with get_db() as db:
        all_trades = list_trades_by_symbol(db, SYMBOL, skip=0, limit=10_000)

    sells = [t for t in all_trades if t.type.lower() == "sell"]
    trades_taken = len(sells)
    wins         = sum(1 for t in sells if (t.pnl or 0) >= 0)
    losses       = sum(1 for t in sells if (t.pnl or 0) <  0)
    net_PnL      = sum(t.pnl or 0 for t in sells)

    # 3) Build and return response
    resp = {
        "running":         running,
        "trades_taken":    trades_taken,
        "current_DV":      algo.DV,
        "net_PnL":         net_PnL,
        "wins":            wins,
        "losses":          losses,
        "prediction_high": algo.prediction_high,
        "prediction_low":  algo.prediction_low,
    }

    logger.info("[algo] | Status: %r", resp)
    return resp

@router.get("/trades")
async def get_trades():
    """
    Return all past trades for the chart markers.
    """
    with get_db() as db:
        all_trades = list_trades_by_symbol(db, SYMBOL, skip=0, limit=1000)

    return [
        {
          # LightweightCharts expects time in seconds:
          "time": int(t.timestamp.timestamp()),
          "price": t.price,
          "type":  t.type.lower(),
        }
        for t in all_trades
    ]

@router.post("/close")
async def close_position():
    """
    Starts the algo in sell-only mode (no buys), and then shuts itself down
    once the currently open position is closed.
    """
    logger.info("[algo] | POST /algo/close called")

    global _algo_task

    # Tell the algo: no more buys, exit after current position closes
    algo.stop_requested = True

    # If it’s not already running, (re)start it
    if not _algo_task or _algo_task.done():
        if not algo.models_ready:
            logger.warning("[algo] | Models not ready; cannot close position")
            raise HTTPException(503, "Prediction models not loaded; cannot run algorithm")

        _algo_task = asyncio.create_task(run_algo())
        logger.info("[algo] | Algorithm task started in sell-only mode")

    return {"status": "closing"}

@router.get("/health")
async def algo_health():
    logger.info("[algo] | GET /algo/health called")
    task_running = bool(_algo_task and not _algo_task.done())
    healthy = algo.models_ready and task_running
    logger.info(
        "[algo] | Health: models_loaded=%s task_running=%s healthy=%s",
        algo.models_ready, task_running, healthy
    )
    return {
        "models_loaded": algo.models_ready,
        "task_running":  task_running,
        "healthy":       healthy
    }


async def shutdown_event():
    logger.info("[algo] | Shutdown event received")
    global _algo_task
    if _algo_task and not _algo_task.done():
        logger.info("[algo] | Cancelling running algorithm task")
        _algo_task.cancel()
        with suppress(asyncio.CancelledError):
            await _algo_task
    _save_trades()
    logger.info("[algo] | Shutdown cleanup complete")


router.add_event_handler("shutdown", shutdown_event)
