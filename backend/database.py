from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    cameras = relationship("Camera", back_populates="owner", cascade="all, delete")
    enrolled_faces = relationship("EnrolledFace", back_populates="owner", cascade="all, delete")
    alert_configs = relationship("AlertConfig", back_populates="owner", cascade="all, delete")


class Camera(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    source = Column(String, nullable=False)   # "0", rtsp://, http://
    status = Column(String, default="offline") # online, offline, error
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="cameras")
    zones = relationship("Zone", back_populates="camera", cascade="all, delete")
    events = relationship("Event", back_populates="camera", cascade="all, delete")


class Zone(Base):
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    name = Column(String, nullable=False)
    zone_type = Column(String, nullable=False)  # polygon, tripwire, speedgate
    points_json = Column(Text, nullable=False)  # JSON array of {x,y} points
    config_json = Column(Text, default="{}")    # dwell_time, crowd_limit, direction, speed_limit, arming_schedule
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    camera = relationship("Camera", back_populates="zones")
    events = relationship("Event", back_populates="zone")


class EnrolledFace(Base):
    __tablename__ = "enrolled_faces"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    encoding_json = Column(Text, nullable=False)  # JSON array of 512 floats
    photo_path = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="enrolled_faces")


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    event_type = Column(String, nullable=False)  # LOITERING, INTRUSION, TRIPWIRE, SPEEDGATE
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String, default="LOW")   # LOW, MEDIUM, HIGH, CRITICAL
    identity = Column(String, default="UNKNOWN")
    object_class = Column(String, default="person")
    confidence = Column(Float, default=0.0)
    frame_path = Column(String, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)
    # ── V4 Metadata Pipeline — rich event attributes ─────────────────────────
    bbox_json = Column(Text, default="")           # "[x1,y1,x2,y2]" bounding box
    direction = Column(String, default="")          # entering, exiting, stationary, crossing
    speed_estimate = Column(String, default="")     # stationary, slow, normal, fast
    dominant_colors = Column(Text, default="")      # '["red","white"]' — top colors from crop
    object_details = Column(Text, default="{}")     # JSON blob for type-specific data
    duration_seconds = Column(Float, default=0.0)   # how long this object has been tracked
    fsm_state = Column(String, default="")          # FSM state at time of event
    camera = relationship("Camera", back_populates="events")
    zone = relationship("Zone", back_populates="events")


class AlertConfig(Base):
    __tablename__ = "alert_configs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alert_type = Column(String, nullable=False)  # sms, call, telegram, discord, slack
    config_json = Column(Text, default="{}")
    active = Column(Boolean, default=True)
    owner = relationship("User", back_populates="alert_configs")


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
