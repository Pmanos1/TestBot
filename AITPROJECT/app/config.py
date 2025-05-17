# app/config.py
import os
from dotenv import load_dotenv

# load the .env file from project root
load_dotenv()

class Settings:
    # KuCoin API credentials
    DATABASE_FILE        = os.getenv("DATABASE_FILE", "/app/trades.db")
    
    LOG_FILE = os.getenv("LOG_FILE", "bot.log")
    PROJECT_TITLE = os.getenv("PROJECT_TITLE", "AIT")

    DEFAULT_PAIR = os.getenv("DEFAULT_PAIR", "KCS-USDT")
    ORDER_TYPE: str = os.getenv("ORDER_TYPE", "market")
    LIMIT_SLIPPAGE: float = float(os.getenv("LIMIT_SLIPPAGE", 0.2))

    KUCOIN_API_KEY       = os.getenv("KUCOIN_API_KEY", "")
    KUCOIN_API_SECRET    = os.getenv("KUCOIN_API_SECRET", "")
    KUCOIN_API_PASSPHRASE= os.getenv("KUCOIN_API_PASSPHRASE", "")
    # Whether to hit the sandbox/testnet endpoints
    SANDBOX              = os.getenv("SANDBOX", "False").lower() in ("1", "true", "yes")

    # Model file paths
    MIN_MODEL_H_PATH     = os.getenv("MIN_MODEL_H_PATH", "minPredHmodel.pkl")
    MIN_MODEL_L_PATH     = os.getenv("MIN_MODEL_L_PATH", "minPredLmodel.pkl")

    # Strategy parameters
    HL_DIFF_THRESHOLD    = float(os.getenv("HL_DIFF_THRESHOLD", 0.002))
    PROFIT_TARGET_MULT   = float(os.getenv("PROFIT_TARGET_MULT", 1.001))
    STOP_LOSS_MULT       = float(os.getenv("STOP_LOSS_MULT", 0.99))
    TIME_STOP_MINUTES    = int(os.getenv("TIME_STOP_MINUTES", 45))


# instantiate a single settings object for import elsewhere
settings = Settings()
