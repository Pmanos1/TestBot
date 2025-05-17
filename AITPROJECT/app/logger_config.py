# app/logger_config.py
import logging
import os
from logging.handlers import RotatingFileHandler

from app.config import settings
LOG_FILE = os.getenv("LOG_FILE", "").strip()

# 1) Create/get your module logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 2) File handler (with rotation)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10_000_000,
    backupCount=5,
    encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)

# 3) Formatter (timestamp + level + message only)
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)
file_handler.setFormatter(formatter)

# 4) Attach to your named logger
logger.addHandler(file_handler)

# 5) (Optional) also log to console
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 6) Apply same handler+formatter to Uvicorn's loggers
for uv_name in ("uvicorn.access", "uvicorn.error"):
    uv_logger = logging.getLogger(uv_name)
    uv_logger.handlers.clear()
    uv_logger.addHandler(file_handler)
    uv_logger.addHandler(console_handler)
    uv_logger.setLevel(logging.INFO)
    uv_logger.propagate = False
