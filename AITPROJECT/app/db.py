# app/db.py

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, desc
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from app.logger_config import logger  # ← added import

# ——————————————————————————————————————————————
# CONFIGURATION
# ——————————————————————————————————————————————
DATABASE_FILE = os.getenv(
    "DATABASE_FILE",
    os.path.join(os.getcwd(), "trades.db")
)

# Ensure the parent directory exists
Path(DATABASE_FILE).parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATABASE_FILE}"

logger.debug(f"[db] Using DATABASE_URL = {DATABASE_URL}")

# Ensure the file (and parent dir) exist before SQLAlchemy touches it
db_dir = os.path.dirname(DATABASE_FILE)
if db_dir and not os.path.isdir(db_dir):
    os.makedirs(db_dir, exist_ok=True)
    logger.debug(f"[db] Created directory for DB: {db_dir}")
if not os.path.exists(DATABASE_FILE):
    open(DATABASE_FILE, "a").close()
    logger.debug(f"[db] Touched new database file: {DATABASE_FILE}")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite only
)
logger.debug("[db] Engine created")

SessionLocal = sessionmaker(
    autoflush=False,
    autocommit=False,
    bind=engine
)

Base = declarative_base()


# ——————————————————————————————————————————————
# MODEL
# ——————————————————————————————————————————————
class Trade(Base):
    __tablename__ = "trades"

    id        = Column(Integer,   primary_key=True, index=True)
    order_id  = Column(String,    nullable=False)     # KuCoin order ID
    status    = Column(String,    nullable=False)     # open, filled, canceled
    type      = Column(String,    nullable=False)     # 'buy' or 'sell'
    symbol    = Column(String,    nullable=False)
    price     = Column(Float,     nullable=False)
    quantity  = Column(Float,     nullable=False)
    timestamp = Column(DateTime,  nullable=False)
    pnl       = Column(Float,     nullable=True)      # profit/loss for a SELL


# ——————————————————————————————————————————————
# INITIALIZATION
# ——————————————————————————————————————————————
def init_db() -> None:
    """Create tables if they don’t exist."""
    logger.info("[db] Initializing database (creating tables if needed)…")
    Base.metadata.create_all(bind=engine)
    logger.info("[db] Database initialized")


# ——————————————————————————————————————————————
# SESSION MANAGEMENT
# ——————————————————————————————————————————————
@contextmanager
def get_db() -> Session:
    """Yield a SQLAlchemy Session, closing it afterwards."""
    logger.debug("[db] Opening new session")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        logger.debug("[db] Session closed")


# ——————————————————————————————————————————————
# CRUD HELPERS
# ——————————————————————————————————————————————
def create_trade(
    db: Session,
    *,
    order_id: str,
    status: str,
    type: str,
    symbol: str,
    price: float,
    quantity: float,
    timestamp: datetime,
    pnl: float | None = None,
) -> Trade:
    """Insert a new trade row into the trades table."""
    logger.debug(f"[db] create_trade → order_id={order_id}, status={status}")
    trade = Trade(
        order_id=order_id,
        status=status,
        type=type,
        symbol=symbol,
        price=price,
        quantity=quantity,
        timestamp=timestamp,
        pnl=pnl,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    logger.info(f"[db] Recorded trade {trade.id} ({order_id}) as {status}")
    return trade


def update_trade_status(
    db: Session,
    order_id: str,
    new_status: str
) -> Trade | None:
    """Update the status of an existing trade by its order_id."""
    logger.debug(f"[db] update_trade_status → order_id={order_id}, new_status={new_status}")
    trade = db.query(Trade).filter(Trade.order_id == order_id).first()
    if trade:
        old = trade.status
        trade.status = new_status
        db.commit()
        db.refresh(trade)
        logger.info(f"[db] Updated trade {trade.id} ({order_id}): {old} → {new_status}")
    else:
        logger.warning(f"[db] update_trade_status: no trade found for order_id={order_id}")
    return trade


def get_trade(db: Session, trade_id: int) -> Trade | None:
    """Return a single trade by its primary key."""
    logger.debug(f"[db] get_trade → id={trade_id}")
    return db.query(Trade).filter(Trade.id == trade_id).first()


def list_trades(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100
) -> list[Trade]:
    """Return a paginated list of trades."""
    logger.debug(f"[db] list_trades → skip={skip} limit={limit}")
    return db.query(Trade).offset(skip).limit(limit).all()


def list_trades_by_symbol(
    db: Session,
    symbol: str,
    *,
    skip: int = 0,
    limit: int = 100
) -> list[Trade]:
    """Return a paginated list of trades filtered by symbol."""
    logger.debug(f"[db] list_trades_by_symbol → symbol={symbol} skip={skip} limit={limit}")
    return (
        db.query(Trade)
          .filter(Trade.symbol == symbol)
          .offset(skip)
          .limit(limit)
          .all()
    )


def get_last_trade_by_symbol(
    db: Session,
    symbol: str
) -> Trade | None:
    """Return the most recent Trade for `symbol`, or None if none exist."""
    logger.debug(f"[db] get_last_trade_by_symbol → symbol={symbol}")
    return (
        db.query(Trade)
          .filter(Trade.symbol == symbol)
          .order_by(desc(Trade.timestamp))
          .first()
    )
