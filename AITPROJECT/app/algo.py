#!/usr/bin/env python3
"""
Algo bot – KuCoin spot

Features:
  * Cancels orders unfilled after 60 seconds
  * Records all orders (open, filled, canceled) with orderId/status in SQLite via app.db
  * Supports MARKET and LIMIT orders (with optional slippage)
  * Floors prices to exact ticks to avoid increment errors
  * Caps order sizes based on available balance
  * Tracks rolling-minute OHLCV for ML-based predictions
"""
import asyncio
import math
import traceback
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN, getcontext

import pandas as pd
from joblib import load
from kucoin.client import Client
from kucoin.asyncio import KucoinSocketManager
from kucoin.exceptions import KucoinAPIException

from app.kc import kc
from app.logger_config import logger
from app.db import (
    get_db,
    create_trade,
    update_trade_status,
    get_last_trade_by_symbol,
    Trade
)
from app.config import settings

from time import time
from sqlalchemy import not_, or_


# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------
SYMBOL             = settings.DEFAULT_PAIR
BASE, QUOTE        = SYMBOL.split("-")

API_KEY            = settings.KUCOIN_API_KEY
API_SECRET         = settings.KUCOIN_API_SECRET
API_PASSPHRASE     = settings.KUCOIN_API_PASSPHRASE

MIN_MODEL_H_PATH   = settings.MIN_MODEL_H_PATH
MIN_MODEL_L_PATH   = settings.MIN_MODEL_L_PATH

HL_DIFF_THRESHOLD  = settings.HL_DIFF_THRESHOLD
PROFIT_TARGET_MULT = settings.PROFIT_TARGET_MULT
STOP_LOSS_MULT     = settings.STOP_LOSS_MULT
TIME_STOP_MINUTES  = settings.TIME_STOP_MINUTES

ORDER_TYPE         = settings.ORDER_TYPE.lower()        # "market" or "limit"
LIMIT_SLIPPAGE     = float(getattr(settings, "LIMIT_SLIPPAGE", 0.001))

# ---------------------------------------------------------------------
# GLOBAL STATE (exposed to UI)
# ---------------------------------------------------------------------
prediction_high: float | None = None
prediction_low:  float | None = None
available_quote: float = 0.0   # e.g. USDT
available_base:  float = 0.0   # e.g. KCS
stop_requested: bool = False   # stop new BUYs, exit after close
_last_known_balances: dict[str, float] = {}

# ---------------------------------------------------------------------
# Precision & Constants
# ---------------------------------------------------------------------
getcontext().prec = 18  # decimal precision
MAX_ORDER_RETRIES    = 5
INITIAL_RETRY_DELAY  = 1  # seconds
BASE_MIN_SIZE = BASE_INCREMENT = PRICE_INCREMENT = 0.0  # populated in run_algo

# ---------------------------------------------------------------------
# Helper: fetch available balance
# ---------------------------------------------------------------------

#------------------ CACHING BALANCES FOR SOME TIME to avoid hammering kucoin ------------
# balance‐cache globals
_last_balance_fetch: float | None = None
_balance_cache: dict[str, float] = {}
BALANCE_CACHE_TTL = 60.0  # seconds
#--------------------------------------------

async def get_available(currency: str) -> float:
    """
    Fetch available balance for `currency`, but only refresh
    from KuCoin if our cache is older than BALANCE_CACHE_TTL.
    Only the 'trade' account entries count toward spendable funds.
    Falls back to last known value.

    Logs every step for full visibility.
    """
    global _last_balance_fetch, _balance_cache

    now = time()
    # Only refresh if cache expired
    if _last_balance_fetch is None or (now - _last_balance_fetch) > BALANCE_CACHE_TTL:
        logger.debug("[algo] | Balance cache stale or empty (last_fetch=%s), fetching fresh…", _last_balance_fetch)
        try:
            loop = asyncio.get_event_loop()
            raw_accounts = await loop.run_in_executor(None, kc.get_accounts)
            logger.debug("[algo] | Raw accounts from KuCoin: %r", raw_accounts)

            # Build cache only from 'trade' entries
            new_cache: dict[str, float] = {}
            for acct in raw_accounts:
                cur = acct.get("currency")
                typ = acct.get("type")
                avail = acct.get("available", "0")
                if cur and typ == "trade":
                    try:
                        new_cache[cur] = float(avail)
                    except Exception:
                        logger.warning("[algo] | Could not parse available=%r for %s", avail, acct)
            _balance_cache = new_cache
            _last_balance_fetch = now
            logger.debug("[algo] | Rebuilt balance cache (trade accounts): %r", _balance_cache)

        except Exception as e:
            logger.warning("[algo] | Balance fetch failed, using cached: %s", e)

    else:
        age = now - _last_balance_fetch
        logger.debug("[algo] | Using cached balances (age=%.1fs)", age)

    # Return the trade‐type available balance for this currency
    val = _balance_cache.get(currency, 0.0)
    logger.debug("[algo] | Returning available[%s] = %.6f", currency, val)
    return val

# ---------------------------------------------------------------------
# Rolling-minute OHLCV buffer
# ---------------------------------------------------------------------
minList = deque(maxlen=5)
current_bar = {
    "minute": None,
    "open":   None,
    "high":   -math.inf,
    "low":     math.inf,
    "close":  None,
    "volume": 0.0
}

# ---------------------------------------------------------------------
# Load ML models
# ---------------------------------------------------------------------
models_ready = False
minH_model = minL_model = None

def load_models():
    global models_ready, minH_model, minL_model
    try:
        minH_model = load(MIN_MODEL_H_PATH)
        minL_model = load(MIN_MODEL_L_PATH)
        models_ready = True
        logger.info("[algo] | Loaded models: %s, %s", MIN_MODEL_H_PATH, MIN_MODEL_L_PATH)
    except Exception as e:
        models_ready = False
        logger.warning("[algo] | Could not load models: %s", e)

load_models()

# ---------------------------------------------------------------------
# Trading state
# ---------------------------------------------------------------------
in_position = False
DV = DV_before_trade = 0.0
BP = SP = exit_price = 0.0
buy_time = high_water = None
wins = losses = 0
total_PnL = 0.0
trades = []

# ---------------------------------------------------------------------
# Helper: floor price to tick
# ---------------------------------------------------------------------
def floor_price_to_tick(p: float) -> str:
    inc = Decimal(str(PRICE_INCREMENT))
    floored = (Decimal(str(p)) // inc) * inc
    return format(floored.quantize(inc, rounding=ROUND_DOWN), 'f')

# ---------------------------------------------------------------------
# Place order with retry & record
# ---------------------------------------------------------------------

async def place_order_with_retry(side: str, price: float | None = None, **kwargs):
    delay = INITIAL_RETRY_DELAY
    for attempt in range(1, MAX_ORDER_RETRIES + 1):
        logger.debug(
            "[algo] | place_order_with_retry: attempt %d/%d for %s (price=%s, size=%s)",
            attempt, MAX_ORDER_RETRIES, side, price, kwargs.get("size")
        )
        try:
            # choose order type
            if ORDER_TYPE == "limit":
                logger.debug("[algo] | ORDER_TYPE=limit")
                if price is None:
                    raise ValueError("Limit orders require a price")
                try:
                    tick = kc.get_ticker(SYMBOL)
                    bd, ba = float(tick["bestBid"]), float(tick["bestAsk"])
                    raw_price = bd * (1 + LIMIT_SLIPPAGE) if side == "buy" else ba * (1 - LIMIT_SLIPPAGE)
                    logger.debug(
                        "[algo] | fetched ticker for slippage: bestBid=%s bestAsk=%s → raw_price=%s",
                        bd, ba, raw_price
                    )
                except Exception as e:
                    raw_price = price
                    logger.warning(
                        "[algo] | failed to fetch ticker for slippage: %s; using price=%s",
                        e, raw_price
                    )
                use_price = floor_price_to_tick(raw_price)
                logger.debug("[algo] | sending LIMIT %s order @ %s size=%s", side, use_price, kwargs["size"])
                raw = kc.create_limit_order(
                    side=side, symbol=SYMBOL,
                    price=use_price, size=kwargs["size"], timeInForce="GTC"
                )
            else:
                logger.debug("[algo] | ORDER_TYPE=market")
                logger.debug("[algo] | sending MARKET %s order size=%s", side, kwargs["size"])
                raw = kc.create_market_order(
                    side=side, symbol=SYMBOL, size=kwargs["size"]
                )

            logger.debug("[algo] | raw response from KuCoin: %r", raw)
            order = raw.get("data", raw)
            logger.debug("[algo] | unwrapped order payload: %r", order)

            rs = (order.get("status") or "").lower()
            logger.debug("[algo] | KuCoin reported status=%r", rs)
            if rs in ("done", "filled"):
                initial_status = "filled"
            elif rs in ("canceled", "cancelled"):
                initial_status = "canceled"
            else:
                initial_status = "open"
            logger.debug("[algo] | normalized initial_status = %r", initial_status)

            oid = order.get("orderId") or order.get("id")
            logger.debug(
                "[algo] | recording trade in DB: order_id=%s, status=%s, side=%s, price=%s, size=%s",
                oid, initial_status, side, price, kwargs["size"]
            )
            with get_db() as db:
                create_trade(
                    db,
                    order_id=oid,
                    status=initial_status,
                    type=side,
                    symbol=SYMBOL,
                    price=float(price or 0),
                    quantity=float(kwargs["size"]),
                    timestamp=datetime.utcnow(),
                    pnl=None
                )

            logger.info("[algo] | %s order placed (ID=%s, status=%s)", side.upper(), oid, initial_status)
            return order

        except Exception as e:
            logger.error(
                "[algo] | %s order attempt %d/%d failed: %s",
                side.upper(), attempt, MAX_ORDER_RETRIES, e,
                exc_info=True
            )
            if attempt == MAX_ORDER_RETRIES:
                logger.error(
                    "[algo] | %s permanently failed after %d attempts",
                    side.upper(), MAX_ORDER_RETRIES
                )
                raise
            logger.debug("[algo] | retrying %s order in %.1f seconds", side, delay)
            await asyncio.sleep(delay)
            delay *= 2


# ─── Confirm fill/cancel & update final status ────────────────────────────
async def place_and_confirm_order(side: str, price: float | None = None, **kwargs):
    logger.debug("[algo] | place_and_confirm_order: side=%s price=%s size=%s", side, price, kwargs.get("size"))
    order = await place_order_with_retry(side, price=price, **kwargs)
    oid = order.get("orderId") or order.get("id")
    logger.debug("[algo] | tracking order_id=%s until filled/canceled", oid)

    start_time = datetime.utcnow()
    while True:
        try:
            raw = await asyncio.get_event_loop().run_in_executor(None, kc.get_order, oid)
            status = raw.get("data", raw)
            logger.debug("[algo] | fetched status for %s: %r", oid, status)
        except KucoinAPIException as e:
            msg = str(e).lower()
            logger.warning("[algo] | error fetching order %s: %s", oid, e)
            if "does not exist" in msg:
                logger.debug("[algo] | order %s not yet indexed, retrying...", oid)
                await asyncio.sleep(0.5)
                continue
            raise

        rs = (status.get("status") or "").lower()
        logger.debug("[algo] | raw status=%r for %s", rs, oid)
        if rs in ("done", "filled"):
            mapped = "filled"
        elif rs in ("canceled", "cancelled"):
            mapped = "canceled"
        else:
            mapped = "open"
        logger.debug("[algo] | mapped status=%r for %s", mapped, oid)

        if not status.get("isActive", False):
            logger.debug("[algo] | order %s is no longer active, updating to %s", oid, mapped)
            with get_db() as db:
                update_trade_status(db, oid, mapped)

            if mapped == "filled":
                logger.info("[algo] | Order %s confirmed filled", oid)
                return status

            logger.warning("[algo] | Order %s ended as %s", oid, mapped)
            raise RuntimeError(f"Order {oid} {mapped}")

        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.debug("[algo] | waiting for %s: elapsed=%.1f/60", oid, elapsed)
        if elapsed > 60:
            logger.warning("[algo] | Order %s timed out after 60s, canceling", oid)
            kc.cancel_order(oid)
            with get_db() as db:
                update_trade_status(db, oid, "canceled")
            raise RuntimeError(f"Order {oid} canceled after timeout")

        await asyncio.sleep(0.5)


# ---------------------------------------------------------------------
# WS message handler
# ---------------------------------------------------------------------
async def handle(msg):
    global prediction_high, prediction_low, in_position, DV_before_trade
    global available_quote, available_base, wins, losses, total_PnL
    global buy_time, high_water, BP, SP, exit_price

    try:
        topic = msg.get("topic","")
        data  = msg.get("data",{})
        if not data:
            return

        # 1) update balances
        available_quote = await get_available(QUOTE)
        available_base  = await get_available(BASE)

        # 2) extract price + ts
        if topic.startswith(f"/market/match:{SYMBOL}"):
            price = float(data.get("price",0)); ts_ns = data.get("time")
        elif topic.startswith(f"/market/ticker:{SYMBOL}"):
            price = float(data.get("bestAsk",data.get("price",0)))
            ts_ns = data.get("time")
        else:
            return

        ts = pd.to_datetime(int(ts_ns),unit="ns")
        minute = ts.floor("min")

        # 3) new minute → finalize previous
        if current_bar["minute"] is None or minute>current_bar["minute"]:
            if current_bar["minute"] is not None:
                minList.append((current_bar["minute"],current_bar.copy()))
                if models_ready and len(minList)>=2:
                    _,b1 = minList[-1]; _,b2 = minList[-2]
                    feat = [
                        b1["open"]/b2["open"],
                        b1["high"]/b1["open"],
                        b1["low"]/b1["open"],
                        b1["close"]/b1["open"],
                        b1["volume"]-b2["volume"]
                    ]
                    X = pd.DataFrame([feat], columns=["open","high","low","close","V"])
                    curH = float(minH_model.predict(X)[0])
                    curL = float(minL_model.predict(X)[0])
                    prediction_high, prediction_low = curH, curL
                    hl_diff = b1["high"]/b1["low"]
                    logger.info("[algo] | PRED H=%.6f L=%.6f hl_diff=%.6f",curH,curL,hl_diff)

                    # ── BUY ───────────────────────────────────────────
                    if (not in_position and not stop_requested
                        and hl_diff>=HL_DIFF_THRESHOLD
                        and curH>=0 and curL>0):

                        if available_quote<=1e-8:
                            logger.error("[algo] | no %s to BUY (bal=%.6f)",QUOTE,available_quote)
                        else:
                            # limit price
                            try:
                                tk = kc.get_ticker(SYMBOL)
                                bb = float(tk["bestBid"])
                                raw_p = bb*(1+LIMIT_SLIPPAGE)
                            except:
                                raw_p = price
                            price_str = floor_price_to_tick(raw_p)
                            price_dec  = Decimal(price_str)

                            # 98% notional cap
                            max_notional = Decimal(str(available_quote))
                            qty_dec      = (max_notional/price_dec).quantize(
                                Decimal(str(BASE_INCREMENT)), rounding=ROUND_DOWN
                            )
                            qty = float(qty_dec)

                            if qty < BASE_MIN_SIZE:
                                logger.warning("[algo] | qty=%.6f < baseMin=%.6f",qty,BASE_MIN_SIZE)
                            else:
                                DV_before_trade = available_quote
                                logger.info("[algo] | 🔵 BUY request qty=%.6f @ %s (bal=%.6f)",
                                            qty, price_str, available_quote)
                                try:
                                    filled = await place_and_confirm_order(
                                        side="buy",
                                        price=float(price_dec),
                                        size=f"{qty:.8f}"
                                    )
                                except Exception as e:
                                    logger.warning("[algo] | BUY failed: %s; continuing", e)
                                else:
                                    fp, fs = float(filled["dealPrice"]), float(filled["dealSize"])
                                    in_position=True; BP=fp; buy_time=ts; high_water=fp
                                    exit_price=BP*PROFIT_TARGET_MULT
                                    logger.info("[algo] | 🔵 BUY FILLED qty=%.6f @ %.6f",fs,fp)

                    # ── SELL ──────────────────────────────────────────
                    elif in_position:
                        if price > high_water:
                            high_water = price
                        #high_water = max(high_water, price)
                        if (price<=high_water*STOP_LOSS_MULT
                            or curH<0
                            or ts>buy_time+timedelta(minutes=TIME_STOP_MINUTES)):

                            raw_q = available_base
                            prec  = max(0,-int(math.log10(BASE_INCREMENT or 1e-6)))
                            qty   = round(math.floor(raw_q/(BASE_INCREMENT or 1e-6))*
                                          (BASE_INCREMENT or 1e-6), prec)
                            if qty<=BASE_MIN_SIZE:
                                logger.error("[algo] | not enough %s to SELL",BASE)
                            else:
                                logger.info("[algo] | 🔴 SELL request qty=%.6f @ market=%.6f",
                                            qty, price)
                                try:
                                    filled = await place_and_confirm_order(
                                        side="sell",
                                        price=price,
                                        size=f"{qty:.8f}"
                                    )
                                except Exception as e:
                                    logger.warning("[algo] | SELL failed: %s; continuing", e)
                                else:
                                    fp, fs = float(filled["dealPrice"]), float(filled["dealSize"])
                                    DV_after = await get_available(QUOTE)
                                    pnl = DV_after - DV_before_trade
                                    in_position=False; wins+=(1 if pnl>=0 else 0)
                                    losses+=(1 if pnl<0 else 0); total_PnL+=pnl
                                    logger.info("[algo] | 🔴 SELL FILLED qty=%.6f @ %.6f pnl=%.6f",
                                                fs,fp,pnl)
                                    with get_db() as db:
                                        create_trade(db,
                                            order_id="N/A",
                                            status="filled",
                                            type="sell",
                                            symbol=SYMBOL,
                                            price=fp,
                                            quantity=fs,
                                            timestamp=ts,
                                            pnl=pnl
                                        )

            # start new bar
            current_bar.update(minute=minute, open=price, high=price,
                               low=price, close=price,
                               volume=float(data.get("size",0)))
        else:
            # update in-progress
            current_bar["high"]  = max(current_bar["high"],price)
            current_bar["low"]   = min(current_bar["low"],price)
            current_bar["close"] = price
            current_bar["volume"]+= float(data.get("size",0))

    except Exception:
        logger.error("[algo] | Exception in handle():\n%s", traceback.format_exc())
        # swallow so minute_ticker keeps running


async def fetch_order_with_retry(order_id: str, max_retries: int = 3, base_delay: float = 0.5):
    """
    Try kc.get_order(order_id) up to max_retries times, with exponential backoff,
    unwrap the 'data' envelope if present, and return the order dict.
    """
    loop = asyncio.get_event_loop()
    for attempt in range(1, max_retries + 1):
        try:
            raw = await loop.run_in_executor(None, kc.get_order, order_id)
            # KuCoin wraps payload under "data"
            return raw.get("data", raw)
        except KucoinAPIException as e:
            logger.warning(
                "[algo] | fetch_order %s attempt %d/%d failed: %s",
                order_id, attempt, max_retries, e
            )
            if attempt == max_retries:
                logger.error("[algo] | Giving up on fetching order %s", order_id)
                raise
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))


async def sync_open_trades():
    """
    Find all trades in the DB whose status isn't yet final
    (i.e. NOT 'filled' or 'canceled'), fetch their real status
    from KuCoin (with retries), update the DB accordingly,
    and log a summary.
    """
    with get_db() as db:
        pending = (
            db.query(Trade)
              .filter(not_(Trade.status.in_(["filled", "canceled"])))
              .all()
        )

    total   = len(pending)
    updated = 0
    logger.info("[algo] | sync_open_trades: found %d trade(s) to sync", total)

    for t in pending:
        logger.debug("[algo] | Checking order %s: local status=%r", t.order_id, t.status)
        try:
            data      = await fetch_order_with_retry(t.order_id)
            logger.info(f"[algo] | Order id's response is : {data}")
            op_type   = (data.get("opType") or "").lower()
            is_active = data.get("isActive", True)
            logger.debug("[algo] | Raw data for %s: %r", t.order_id, data)
        except Exception as e:
            logger.warning("[algo] | Could not fetch order %s: %s", t.order_id, e)
            continue

        # if still active, skip
        if is_active:
            logger.debug("[algo] |   → order %s still active on KuCoin", t.order_id)
            continue

        # map opType to our status
        if op_type == "deal":
            real_status = "filled"
        elif op_type == "cancel":
            real_status = "canceled"
        else:
            real_status = "open"

        if real_status != t.status:
            logger.info(
                "[algo] |   → update %s: %r → %r",
                t.order_id, t.status, real_status
            )
            with get_db() as db:
                update_trade_status(db, t.order_id, real_status)
            updated += 1

            # bootstrap in_position if a BUY just filled
            if t.type.lower() == "buy" and real_status == "filled":
                global in_position, BP, buy_time, high_water, exit_price, DV_before_trade
                in_position     = True
                BP              = t.price
                buy_time        = t.timestamp
                high_water      = BP
                exit_price      = BP * PROFIT_TARGET_MULT
                DV_before_trade = await get_available(QUOTE)
                logger.info("[algo] | Restored in-position: BUY @ %.6f", BP)
        else:
            logger.debug("[algo] |   → no change for %s (still %r)", t.order_id, t.status)

    logger.info(
        "[algo] | sync_open_trades complete: %d/%d trade(s) updated",
        updated, total
    )


# ---------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------
async def run_algo():
    global BASE_MIN_SIZE, BASE_INCREMENT, PRICE_INCREMENT

    syms = kc.get_symbols()
    entry = next((s for s in syms if s["symbol"] == SYMBOL), None)
    if not entry:
        raise RuntimeError(f"Symbol {SYMBOL} not found")

    BASE_MIN_SIZE   = float(entry["baseMinSize"])
    BASE_INCREMENT  = float(entry["baseIncrement"])
    PRICE_INCREMENT = float(entry["priceIncrement"])
    logger.info(
        "[algo] | Tick sizes → baseMin=%.8f baseInc=%.8f priceInc=%.8f",
        BASE_MIN_SIZE, BASE_INCREMENT, PRICE_INCREMENT
    )

    logger.info("Trying to sync-up any open order's in our db with actual status from Kucoin side...")
    await sync_open_trades()
    logger.info("Trying to sync-up any open order's in our db with actual status from Kucoin side...")
    

    # Resume open BUY only if it was already marked as 'filled'
    with get_db() as db:
        last = get_last_trade_by_symbol(db, SYMBOL)
    if last and last.type.lower() == "buy" and last.status == "filled":
        global in_position, BP, buy_time, high_water, exit_price
        in_position = True
        BP          = last.price
        buy_time    = last.timestamp
        high_water  = BP
        exit_price  = BP * PROFIT_TARGET_MULT
        logger.info("[algo] | Resumed BUY @ %.6f time=%s", BP, buy_time)

    logger.info("[algo] | Connecting to KuCoin feeds for %s", SYMBOL)
    loop   = asyncio.get_event_loop()
    client = Client(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=API_PASSPHRASE
    )
    ksm = await KucoinSocketManager.create(loop, client, handle, private=False)
    await ksm.subscribe(f"/market/match:{SYMBOL}")
    await ksm.subscribe(f"/market/ticker:{SYMBOL}")

    async def minute_ticker():
        while True:
            now    = pd.Timestamp.utcnow()
            target = now.ceil("min") + pd.Timedelta(seconds=0.5)
            await asyncio.sleep((target - now).total_seconds())
            await sync_open_trades()
            await handle({
                "topic": f"/market/ticker:{SYMBOL}",
                "data": {
                    "price": current_bar["close"],
                    "time":  int(pd.Timestamp.utcnow().value)
                }
            })

    asyncio.create_task(minute_ticker())

    try:
        while True:
            await asyncio.sleep(0.2)
            if stop_requested and not in_position:
                logger.info("[algo] | Sell-only complete; shutting down")
                break
    finally:
        await ksm.close()


if __name__=="__main__":
    try:
        asyncio.run(run_algo())
    except KeyboardInterrupt:
        logger.info("[algo] | Interrupted; saving trades…")
        pd.DataFrame(trades).to_csv("live_trades.csv",index=False)
        logger.info("[algo] | Saved %d trades DV=%.6f wins=%d losses=%d",
                    len(trades), DV, wins, losses)
