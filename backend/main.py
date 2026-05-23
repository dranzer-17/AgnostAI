import os
import logging
import logging.handlers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from api.webhook import router as webhook_router
from api.insights import router as insights_router

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../.env"))

# ── Logging setup ──────────────────────────────────────────────────────────────
os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
log_path = os.path.join(os.path.dirname(__file__), "logs", "app.log")

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Rotating file handler — 5MB per file, keep last 5
file_handler = logging.handlers.RotatingFileHandler(
    log_path, maxBytes=5 * 1024 * 1024, backupCount=5
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Suppress noisy uvicorn access logs from duplicating
logging.getLogger("uvicorn.access").handlers = []
logging.getLogger("uvicorn.access").propagate = True

logger = logging.getLogger("agnost")
logger.info(f"Starting Agnost Voice Analytics — logs at {log_path}")

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Agnost Voice Analytics")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router, prefix="/api")
app.include_router(insights_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
