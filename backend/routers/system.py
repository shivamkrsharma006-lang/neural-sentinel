import logging
from fastapi import APIRouter, Depends
from auth import get_current_user
from agents.detection_agent import detection_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])

@router.get("/status")
def get_system_status(current_user=Depends(get_current_user)):
    # logger.debug(f"System status requested: armed={detection_agent._armed}")
    return {"armed": detection_agent._armed}

@router.post("/arm")
def arm_system(current_user=Depends(get_current_user)):
    logger.info(f"Received ARM command from user {current_user.username}")
    detection_agent.arm()
    return {"armed": True}

@router.post("/disarm")
def disarm_system(current_user=Depends(get_current_user)):
    logger.info(f"Received DISARM command from user {current_user.username}")
    detection_agent.disarm()
    return {"armed": False}
