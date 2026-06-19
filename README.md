# Neural Sentinel v3.0 🛡️
### Hardware-Agnostic Multi-Agent AI Surveillance System

> **Patent Pending** — A Multi-Agent Video Surveillance System with Closed-Loop Risk-Proportional Inference Scheduling, Post-Inference Metadata Deduplication, Non-Linear Temporal Risk Accumulation with Hysteresis, and Multi-Frame Biometric Embedding Averaging.

---

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+ (for frontend)
- Webcam or IP camera

### 1. Start everything (Windows)
```bash
# Just double-click:
start.bat
```

### 2. Manual start

**Backend:**
```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

**Access:** http://localhost:5173

---

## Architecture — The V2 Pipeline

Neural Sentinel operates on a highly advanced, mathematically rigorous 3-Agent architecture designed for optimal CPU utilization without GPUs:

### 1. Detection Agent (Vision & Scheduling)
- **Risk-Proportional Closed-Loop Scheduler**: Dynamically allocates inference cycles using a recurrence equation: `U(c,t) = max(U_min, α·V(c,t) + β·U(c,t−1)·e^(−λ·Δt))`. It feeds the logistic risk score `R_max` back into the scheduler to eliminate inference starvation during extended entity dwell.
- **Post-Inference Metadata Deduplication**: A single physical stream is AI-evaluated exactly once. The resulting metadata is forked with hardware timestamps, enforcing causal consistency and stale-drop across rule evaluators.
- **Motion Gating**: Uses pixel-level differences to skip heavy YOLOv8 inference when the scene is static, reusing previous metadata.

### 2. Decision Agent (Logic & Threat Assessment)
- **Two-Tiered Confidence Gate**: `θ_track` (e.g., 0.35) maintains tracking continuity during partial occlusion, while `θ_alert` (e.g., 0.55) is a hard precondition for THREAT escalation. 
- **Non-Linear Temporal Risk Accumulation**: Computes a continuous severity integral: `S(id,t) = Σ C_i · (1−A(id,t)) · e^(−γ·(t−t_i))` and passes it through a logistic sigmoid curve: `R(id,t) = 1 / (1 + e^(−k·(S(id,t)−0.5)))`. This ensures older frames decay exponentially.
- **Adversarial Hysteresis Protection**: If an object exits a zone, a suspended-exit sub-state preserves their `S(id,t)` for `H_seconds`, preventing severity-reset exploits via momentary boundary exits.
- **Multi-Frame Biometric Averaging**: Collects up to 3 face embeddings, applies CLAHE and Laplacian blur rejection, averages them, and computes L2-normalized cosine similarity. Upon a match, `A(id,t) = 1.0` immediately retroactively nullifies the accumulated severity `S(id,t)`.

### 3. Response Agent (Action & Notification)
- **Event Dispatch**: Persists JPEG evidence to memory and disk, logs structured JSON to SQLite, and broadcasts via WebSockets.
- **Per-Track Event Cooldown**: Dispatches throttled multi-channel alerts (SMS, Telegram, Discord, Slack) without interrupting the continuous mathematical integrity of the risk score.

---

## Features

| Feature | Status |
|---------|--------|
| Risk-Proportional Closed-Loop Scheduler | ✅ |
| Post-Inference Metadata Deduplication | ✅ |
| Two-Tiered Confidence Gate (θ_track / θ_alert) | ✅ |
| Non-Linear Temporal Risk Score with Hysteresis | ✅ |
| Multi-Frame Biometric Embedding Averaging | ✅ |
| Polygon zone detection & Tripwires | ✅ |
| Temporal arming schedules | ✅ |
| 5-state per-object FSM | ✅ |
| Face enrollment (InsightFace) | ✅ |
| Multi-user auth (JWT) | ✅ |
| MJPEG stream with overlay | ✅ |
| Browser-based zone drawing | ✅ |
| Evidence frame capture | ✅ |
| Twilio SMS + Call | ✅ |
| Telegram / Discord / Slack | ✅ |
| LAN remote access & Tailscale | ✅ |

---

## Face Recognition

Uses **InsightFace** (ONNX Runtime, no dlib, Windows-friendly):
```bash
pip install insightface onnxruntime
```
*Features background model pre-warming to eliminate cold-start biometric latency.*

---

## Remote Access

**Same WiFi (phone monitoring):**
1. Find laptop IP: `ipconfig` → IPv4 Address
2. Open `http://<laptop-ip>:5173` on phone

**From anywhere (Tailscale):**
1. Install Tailscale on laptop + phone
2. Use Tailscale IP instead of local IP

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

```env
SECRET_KEY=your-secret-key
TWILIO_ACCOUNT_SID=ACxxxx
TWILIO_AUTH_TOKEN=xxxx
TWILIO_FROM_NUMBER=+1234567890
TELEGRAM_BOT_TOKEN=xxxx
TELEGRAM_CHAT_ID=xxxx
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

---

*Neural Sentinel — Patent Pending | Built on YOLOv8 + InsightFace + FastAPI + React*
