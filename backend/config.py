import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
FRAMES_DIR = DATA_DIR / "frames"
DB_PATH = DATA_DIR / "neural_sentinel.db"

FRAMES_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.getenv("SECRET_KEY", "neural-sentinel-default-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

DATABASE_URL = f"sqlite:///{DB_PATH}"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

YOLO_MODEL = os.getenv("YOLO_MODEL", "yolov8n.pt")
FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.40"))


# ── Scheduler parameters — U(c,t) = max(U_min, α·V(c,t) + β·U(c,t−1)·e^(−λ·Δt)) ──
SCHED_ALPHA   = float(os.getenv("SCHED_ALPHA",   "1.0"))   # spike multiplier on violation
SCHED_BETA    = float(os.getenv("SCHED_BETA",    "0.9"))   # historical retention factor
SCHED_LAMBDA  = float(os.getenv("SCHED_LAMBDA",  "2.0"))   # exponential decay constant
SCHED_U_MIN   = float(os.getenv("SCHED_U_MIN",   "0.1"))   # minimum fairness floor

# ── Confidence gates (two-tiered) ─────────────────────────────────────────────
THETA_TRACK   = float(os.getenv("THETA_TRACK",   "0.35"))  # minimum for tracker continuity
THETA_ALERT   = float(os.getenv("THETA_ALERT",   "0.55"))  # minimum for THREAT transition

# ── Risk model — R(id,t) = 1/(1+e^(−k·(S(id,t)−0.5))) ──────────────────────
# S(id,t) = Σ C_i · (1−A(id)) · e^(−γ·(t−t_i))   ← negative exponent (intentional: temporal locality)

RISK_GAMMA     = float(os.getenv("RISK_GAMMA",    "0.5"))   # temporal compounding rate
RISK_K         = float(os.getenv("RISK_K",        "6.0"))   # logistic steepness
RISK_THRESHOLD = float(os.getenv("RISK_THRESHOLD","0.6"))   # R_threshold for alert dispatch

# ── Alert cooldown ────────────────────────────────────────────────────────────
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "30"))

CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000", "*"]

