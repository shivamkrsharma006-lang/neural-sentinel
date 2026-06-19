from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db, AlertConfig, User
from auth import get_current_user
from models.schemas import AlertConfigCreate, AlertConfigOut
from agents.response_agent import response_agent

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _refresh(db: Session):
    configs = db.query(AlertConfig).filter(AlertConfig.active == True).all()
    response_agent.refresh_alert_configs([
        {"alert_type": c.alert_type, "config_json": c.config_json, "active": c.active}
        for c in configs
    ])


@router.get("", response_model=List[AlertConfigOut])
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return db.query(AlertConfig).filter(AlertConfig.user_id == current_user.id).all()


@router.post("", response_model=AlertConfigOut)
def create_alert(
    payload: AlertConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cfg = AlertConfig(
        user_id=current_user.id,
        alert_type=payload.alert_type,
        config_json=payload.config_json,
        active=payload.active,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    _refresh(db)
    return cfg


@router.put("/{alert_id}", response_model=AlertConfigOut)
def update_alert(
    alert_id: int,
    payload: AlertConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cfg = db.query(AlertConfig).filter(
        AlertConfig.id == alert_id, AlertConfig.user_id == current_user.id
    ).first()
    if not cfg:
        raise HTTPException(404, "Alert config not found")
    cfg.alert_type = payload.alert_type
    cfg.config_json = payload.config_json
    cfg.active = payload.active
    db.commit()
    db.refresh(cfg)
    _refresh(db)
    return cfg


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cfg = db.query(AlertConfig).filter(
        AlertConfig.id == alert_id, AlertConfig.user_id == current_user.id
    ).first()
    if not cfg:
        raise HTTPException(404, "Alert config not found")
    db.delete(cfg)
    db.commit()
    _refresh(db)
    return {"ok": True}
