"""
Neural Sentinel — FastAPI Application Entry Point

Startup sequence:
  1. Create DB tables
  2. Start DetectionAgent (loads YOLOv8, starts inference thread)
  3. Wire DetectionAgent → DecisionAgent → ResponseAgent callbacks
  4. Reload all cameras and zones from DB
  5. Reload enrolled faces
  6. Refresh alert configs
"""

import asyncio
import json
import logging
import threading
import numpy as np
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from config import CORS_ORIGINS, FRAMES_DIR
from database import create_tables, SessionLocal, Camera, Zone, EnrolledFace, AlertConfig
from agents.detection_agent import detection_agent
from agents.decision_agent import decision_agent
from agents.response_agent import response_agent, set_event_loop
from routers import auth, cameras, zones, events, faces, stream, alerts, system, digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _startup_sync():
    """Synchronous startup: DB, agents, data loading."""
    create_tables()
    logger.info("Database tables ready")

    # Run biometric database migration to ONNX ArcFace
    try:
        from utils.migrate_biometrics import run_migration
        run_migration()
    except Exception as e:
        logger.error(f"Startup biometric migration failed: {e}")


    # Wire agent pipeline: detection → decision → response
    detection_agent.register_callback(decision_agent.process)
    decision_agent.register_callback(response_agent.handle_violation)
    response_agent.set_db_factory(SessionLocal)

    # Start detection agent (loads YOLO, starts threads)
    detection_agent.start()

    db = SessionLocal()
    try:
        # Load all cameras into detection agent
        for cam in db.query(Camera).all():
            detection_agent.add_camera(cam.id, cam.source, name=cam.name)

        # Load all zones into decision agent
        for cam in db.query(Camera).all():
            zones_data = db.query(Zone).filter(Zone.camera_id == cam.id).all()
            decision_agent.set_zones(cam.id, [
                {
                    "id": z.id, "name": z.name, "zone_type": z.zone_type,
                    "points_json": z.points_json, "config_json": z.config_json,
                    "active": z.active,
                }
                for z in zones_data
            ])

        # Load enrolled faces
        faces_data = db.query(EnrolledFace).all()
        enrolled = []
        for f in faces_data:
            try:
                emb = np.array(json.loads(f.encoding_json), dtype=np.float32)
                enrolled.append((f.name, emb))
            except Exception:
                pass
        decision_agent.set_enrolled_faces(enrolled)
        logger.info(f"Loaded {len(enrolled)} enrolled faces")

        # Load alert configs
        alert_cfgs = db.query(AlertConfig).filter(AlertConfig.active == True).all()
        response_agent.refresh_alert_configs([
            {"alert_type": c.alert_type, "config_json": c.config_json, "active": c.active}
            for c in alert_cfgs
        ])
    finally:
        db.close()

    # Pre-warm ArcFace model in background — eliminates 3-8 min cold-start delay
    # Server starts immediately; model is ready within ~60s of startup.
    def _prewarm():
        from utils.face_utils import prewarm_model
        prewarm_model()
    threading.Thread(target=_prewarm, daemon=True, name="face-prewarm").start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    loop = asyncio.get_running_loop()
    set_event_loop(loop)
    _startup_sync()
    logger.info("Neural Sentinel started 🚀")
    yield
    # Shutdown
    detection_agent.stop()
    logger.info("Neural Sentinel stopped")


app = FastAPI(
    title="Neural Sentinel API",
    description="Multi-agent AI surveillance system",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(zones.router)
app.include_router(events.router)
app.include_router(faces.router)
app.include_router(alerts.router)
app.include_router(stream.router)
app.include_router(system.router)
app.include_router(digest.router)

# ── Serve evidence frames from disk (fallback removed for security; served via authenticated API) ───────


@app.middleware("http")
async def rewrite_api_requests(request: Request, call_next):
    path = request.scope.get("path", "")
    if path.startswith("/api/"):
        request.scope["path"] = path[4:]
    return await call_next(request)

@app.get("/api")
def root():
    return {
        "name": "Neural Sentinel",
        "version": "3.0.0",
        "status": "running",
        "cameras_active": len(detection_agent._captures),
    }

@app.get("/health")
def health():
    return {"status": "ok"}

# ── Serve React Frontend ───────────────────────────────────────────────────────
dist_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(dist_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(dist_path, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Ignore API and media paths, let them 404 if not caught by routers
        if full_path.startswith("api/") or full_path.startswith("stream/") or full_path.startswith("ws/") or full_path.startswith("frames/"):
            raise HTTPException(status_code=404, detail="Not found")
        
        # Serve index.html for all other paths (React Router)
        index_file = os.path.join(dist_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="Frontend build not found")
else:
    @app.get("/")
    def no_frontend():
        return {"error": "Frontend build not found. Run 'npm run build' in frontend directory."}
