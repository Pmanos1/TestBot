# app/kc.py
import asyncio
import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from kucoin.client import Client
from kucoin.exceptions import KucoinAPIException
from app.logger_config import logger
from app.db import get_db, get_last_trade_by_symbol


router = APIRouter(prefix="/kc", tags=["kucoin"])

# ─── CONFIG ────────────────────────────────────────────────────────────────
from app.config import settings

API_KEY        = settings.KUCOIN_API_KEY
API_SECRET     = settings.KUCOIN_API_SECRET
API_PASSPHRASE = settings.KUCOIN_API_PASSPHRASE
SANDBOX        = settings.SANDBOX

# ─── CONFIG ────────────────────────────────────────────────────────────────

kc = Client(
    api_key    = API_KEY,
    api_secret = API_SECRET,
    passphrase = API_PASSPHRASE,
    sandbox    = SANDBOX
)

# ─── MODELS ────────────────────────────────────────────────────────────────
class MarketOrderRequest(BaseModel):
    symbol: str
    funds:  str

class PollOrderRequest(BaseModel):
    symbol:   str
    order_id: str

class MarketSellRequest(BaseModel):
    symbol: str
    size:   str

class LimitOrderRequest(BaseModel):
    symbol: str
    price:  str
    size:   str

# ─── HEALTH CHECK ──────────────────────────────────────────────────────────
@router.get("/health")
async def kucoin_health(request: Request):
    logger.info("[kc] | GET /kc/health called from %s", request.client.host)
    try:
        resp = kc.get_status()
        data = resp.get("data", {})
        logger.info("[kc] | KuCoin status: %s", data)
        return {"status": "ok", "service_status": data}
    except KucoinAPIException as e:
        logger.error("[kc] | KuCoinAPIException in /health: %s", e)
        raise HTTPException(502, f"KuCoin API error: {e}")
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /health")
        raise HTTPException(500, f"Health check failed: {e}")

# ─── BALANCES ──────────────────────────────────────────────────────────────
@router.get("/balances")
async def get_nonzero_balances(request: Request):
    logger.info("[kc] | GET /kc/balances called from %s", request.client.host)
    try:
        result = []
        for acct in kc.get_accounts():
            bal   = float(acct["balance"])
            avail = float(acct.get("available", 0))
            if bal > 0:
                result.append({
                    "currency":  acct["currency"],
                    "balance":   bal,
                    "available": avail
                })
        logger.info("[kc] | Returning %d non-zero balances", len(result))
        return {"balances": result}
    except Exception as e:
        logger.exception("[kc] | Error fetching balances")
        raise HTTPException(500, f"Error fetching balances: {e}")

# ─── TICKER ────────────────────────────────────────────────────────────────
@router.get("/ticker/{symbol}")
async def get_ticker(symbol: str, request: Request):
    logger.info("[kc] | GET /kc/ticker/%s called from %s", symbol, request.client.host)
    try:
        data = kc.get_ticker(symbol)
        price = float(data["price"])
        logger.info("[kc] | Ticker %s price: %s", symbol, price)
        return {"symbol": symbol, "price": price}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /ticker: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /ticker")
        raise HTTPException(500, str(e))

# ─── MARKET BUY ────────────────────────────────────────────────────────────
@router.post("/order/market-buy")
async def market_buy(req: MarketOrderRequest, request: Request):
    logger.info("[kc] | POST /kc/order/market-buy called: %s", req.json())
    try:
        order = kc.create_market_order(
            symbol=req.symbol, side="buy", funds=req.funds
        )
        oid = order.get("orderId")
        status = order.get("status")
        logger.info("[kc] | Market buy placed: orderId=%s status=%s", oid, status)
        return {"orderId": oid, "status": status}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /market-buy: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /market-buy")
        raise HTTPException(500, str(e))

# ─── POLL ORDER ───────────────────────────────────────────────────────────
@router.post("/order/poll")
async def poll_order(req: PollOrderRequest, request: Request):
    logger.info("[kc] | POST /kc/order/poll called: %s", req.json())
    oid = req.order_id
    sym = req.symbol
    try:
        for i in range(30):
            info = kc.get_order(oid, symbol=sym)
            if not info.get("isActive", True):
                logger.info("[kc] | Order %s filled after %d checks", oid, i+1)
                return {"orderId": oid, "filled": True}
            await asyncio.sleep(1)
        logger.warning("[kc] | Order %s not filled after timeout", oid)
        return {"orderId": oid, "filled": False, "message": "timeout"}
    except Exception as e:
        logger.exception("[kc] | Error polling order")
        raise HTTPException(500, str(e))

# ─── CANCEL ORDER ─────────────────────────────────────────────────────────
@router.post("/order/cancel/{order_id}")
async def cancel_order(order_id: str, request: Request):
    logger.info("[kc] | POST /kc/order/cancel/%s called", order_id)
    try:
        kc.cancel_order(order_id)
        logger.info("[kc] | Order %s canceled", order_id)
        return {"orderId": order_id, "canceled": True}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /cancel: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /cancel")
        raise HTTPException(500, str(e))

# ─── GET FILLS ────────────────────────────────────────────────────────────
@router.get("/order/fills/{symbol}/{order_id}")
async def get_fills(symbol: str, order_id: str, request: Request):
    logger.info("[kc] | GET /kc/order/fills/%s/%s called", symbol, order_id)
    try:
        fills = kc.get_fills(symbol=symbol, order_id=order_id)
        logger.info("[kc] | Returning %d fills for %s", len(fills), order_id)
        return {"symbol": symbol, "orderId": order_id, "fills": fills}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /fills: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /fills")
        raise HTTPException(500, str(e))

# ─── ORDER HISTORY (all symbols) ───────────────────────────────────────────
@router.get("/orders")
async def get_all_orders(request: Request, limit: int = 20):
    logger.info("[kc] | GET /kc/orders?limit=%d from %s", limit, request.client.host)

    def extract_items(resp: dict):
        if "items" in resp:
            return resp["items"]
        if isinstance(resp.get("data"), dict):
            return resp["data"].get("items", [])
        return []

    try:
        resp_active  = kc.get_orders(symbol=None, status="active", page=1, limit=limit)
        items_active = extract_items(resp_active)
        resp_done    = kc.get_orders(symbol=None, status="done",   page=1, limit=limit)
        items_done   = extract_items(resp_done)

        all_items = items_active + items_done
        all_items.sort(key=lambda o: o.get("createdAt", 0), reverse=True)
        trimmed   = all_items[:limit]

        logger.info("[kc] | Returning %d orders (active+done)", len(trimmed))
        return {"orders": trimmed}

    except KucoinAPIException as e:
        logger.error("[kc] | KuCoinAPIException in /orders: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Error in /orders")
        raise HTTPException(500, str(e))

@router.get("/orders/active_status")
async def has_active_orders(request: Request):
    logger.info("[kc] | GET /kc/orders/active_status from %s", request.client.host)
    try:
        resp = kc.get_orders(symbol=None, status="active", page=1, limit=10)
        items = resp.get("items") or resp.get("data", {}).get("items", [])
        return {"has_active_orders": len(items) > 0}
    except KucoinAPIException as e:
        logger.error("[kc] | KuCoinAPIException in /orders/active_status: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Error in /orders/active_status")
        raise HTTPException(500, str(e))

# ─── TRADE HISTORY ─────────────────────────────────────────────────────────
@router.get("/trade-history/{symbol}")
async def get_trade_history(symbol: str, request: Request):
    client_ip = request.client.host
    sym = symbol.strip().upper()
    logger.info("[kc] | GET /kc/trade-history/%s from %s", sym, client_ip)

    try:
        trades = kc.get_trade_histories(sym)
        if not trades:
            alt = sym.replace("-", "_")
            if alt != sym:
                logger.info("[kc] | No trades for %s, retrying with %s", sym, alt)
                trades = kc.get_trade_histories(alt)
        logger.info("[kc] | Returning %d trades for %s", len(trades), sym)
        return {"symbol": sym, "trades": trades}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /trade-history: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /trade-history")
        raise HTTPException(500, f"Error fetching trade history: {e}")

@router.get("/my-fills")
async def get_my_fills(request: Request, limit: int = 20):
    logger.info("[kc] | GET /kc/my-fills?limit=%d from %s", limit, request.client.host)
    try:
        resp = kc.get_orders(symbol=None, status="done", page=1, limit=limit)
        orders = resp.get("items", [])

        fills = []
        for o in orders:
            fills.append({
                "orderId":     o["id"],
                "symbol":      o["symbol"],
                "side":        o["side"],
                "orderType":   o["type"],
                "size":        o["size"],
                "dealSize":    o["dealSize"],
                "funds":       o["funds"],
                "dealFunds":   o["dealFunds"],
                "fee":         o["fee"],
                "feeCurrency": o["feeCurrency"],
                "createdAt":   o["createdAt"],
            })

        return {"fills": fills}

    except KucoinAPIException as e:
        logger.error("[kc] | Error in /my-fills: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /my-fills")
        raise HTTPException(500, str(e))

# ─── MARKET SELL ───────────────────────────────────────────────────────────
@router.post("/order/market-sell")
async def market_sell(req: MarketSellRequest, request: Request):
    logger.info("[kc] | POST /kc/order/market-sell called: %s", req.json())
    try:
        order = kc.create_market_order(
            symbol=req.symbol, side="sell", size=req.size
        )
        oid    = order.get("orderId")
        status = order.get("status")
        logger.info("[kc] | Market sell placed: orderId=%s status=%s", oid, status)
        return {"orderId": oid, "status": status}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /market-sell: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /market-sell")
        raise HTTPException(500, str(e))

# ─── LIMIT BUY ──────────────────────────────────────────────────────────────
@router.post("/order/limit-buy")
async def limit_buy(req: LimitOrderRequest, request: Request):
    logger.info("[kc] | POST /kc/order/limit-buy called: %s", req.json())
    try:
        order = kc.create_limit_order(
            symbol=req.symbol,
            side="buy",
            price=req.price,
            size=req.size
        )
        oid    = order.get("orderId") or order.get("order_id")
        status = order.get("status")
        logger.info("[kc] | Limit buy placed: orderId=%s status=%s", oid, status)
        return {"orderId": oid, "status": status}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /limit-buy: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /limit-buy")
        raise HTTPException(500, str(e))

# ─── LIMIT SELL ─────────────────────────────────────────────────────────────
@router.post("/order/limit-sell")
async def limit_sell(req: LimitOrderRequest, request: Request):
    logger.info("[kc] | POST /kc/order/limit-sell called: %s", req.json())
    try:
        order = kc.create_limit_order(
            symbol=req.symbol,
            side="sell",
            price=req.price,
            size=req.size
        )
        oid    = order.get("orderId") or order.get("order_id")
        status = order.get("status")
        logger.info("[kc] | Limit sell placed: orderId=%s status=%s", oid, status)
        return {"orderId": oid, "status": status}
    except KucoinAPIException as e:
        logger.error("[kc] | KucoinAPIException in /limit-sell: %s", e)
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[kc] | Unexpected error in /limit-sell")
        raise HTTPException(500, str(e))

@router.get("/orders/open_position")
async def has_open_position(request: Request):
    """
    Return true if our last trade in the DB was a BUY (i.e. we have an open position),
    false otherwise.
    """
    logger.info("[kc] | GET /kc/orders/open_position from %s", request.client.host)
    with get_db() as db:
        last = get_last_trade_by_symbol(db, settings.DEFAULT_PAIR)

    has_open = bool(last and last.type.lower() == "buy")
    return {"has_open_position": has_open}