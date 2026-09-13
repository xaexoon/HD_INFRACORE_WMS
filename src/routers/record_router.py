from fastapi import APIRouter
from pydantic import BaseModel
from src.schemas import response_schema, record_schema
from src.schemas.record_schema import AmrRecordLog
from src.services import record_service
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("api.record")


@router.post("/insert/wash/log")
def insert_wash_log(body: record_schema.AmrRecordLog):
    """세척 AMR 이력 수신."""
    seq = record_service.insert_wash_log(body)
    return response_schema.response(True, "이력 등록 완료", {"seq": seq})