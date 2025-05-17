# app/kclivefeed.py
"""
run_ws(pair, stop_evt)
  • streams KuCoin /market/match:<pair> ticks
  • publishes into in-memory broadcaster channel price_feed:<pair>
"""

import asyncio, sys, traceback
from kucoin.client import Client
from kucoin.asyncio import KucoinSocketManager
from app.pubsub import broadcast
from app.logger_config import logger

async def run_ws(pair: str, stop_evt: asyncio.Event):
    loop = asyncio.get_event_loop()
    # public data only; no creds needed
    client = Client(api_key="", api_secret="", passphrase="")

    topic   = f"/market/match:{pair}"
    channel = f"price_feed:{pair}"

    async def handle(msg):
        if stop_evt.is_set():
            return  # bail early if asked to stop

        # only forward real match data
        if msg.get("topic") == topic and msg.get("data"):
            d       = msg["data"]
            ts      = d.get("time")
            price   = d.get("price")
            size    = d.get("size", "")
            payload = f"{ts},{price},{size}"

            # publish via in-memory broadcaster
            await broadcast.publish(channel=channel, message=payload)
            logger.debug("[kclive] | TICK %s  %s", pair, payload)

    logger.info("[kclive] | 🚀 Connecting WS for %s", pair)
    ksm = None
    try:
        ksm = await KucoinSocketManager.create(loop, client, handle, private=False)
        await ksm.subscribe(topic)

        # keep the subscription alive until stopped
        while not stop_evt.is_set():
            await asyncio.sleep(0.2)

    except Exception:
        logger.error(
            "[kclive] | ⚠️ WS task crashed for %s:\n%s",
            pair,
            traceback.format_exc()
        )

    finally:
        if ksm:
            # clean unsubscribe & close
            try:
                await ksm.unsubscribe(topic)
            except Exception:
                pass
            try:
                await ksm.close()
            except Exception:
                pass

        logger.info("[kclive] | 🔌 WS task finished for %s", pair)


if __name__ == "__main__":
    async def _test():
        evt  = asyncio.Event()
        pair = sys.argv[1] if len(sys.argv) > 1 else "BTC-USDT"
        await run_ws(pair, evt)

    asyncio.run(_test())
