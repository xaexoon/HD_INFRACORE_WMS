import json
from datetime import datetime

from src.db.connection import insert_returning
from src.queries import record_query
from src.schemas import record_schema
from src.logger.logger import get_logger

logger = get_logger("svc.record")


def insert_wash_log(body: record_schema.AmrRecordLog) -> int:
    """ACS/QR PC 가 보내는 값을 그대로 남긴다.

    status 는 검증하지 않는다 — 상태 정의의 주인이 저쪽이므로
    값이 추가될 때마다 INSERT 가 터지면 이력이 아예 안 쌓인다.
    """
    rows = insert_returning(record_query.INSERT_WASH_LOG, (
        body.job_type,
        body.pallet_no,
        body.model,
        body.engine_no,
        json.dumps(body.w_lpn_list, ensure_ascii=False) if body.w_lpn_list else None,
        body.status,
        body.status_date or datetime.now(),
        body.remark,
    ))
    seq = rows[0]["seq"]
    logger.info("세척 이력 %s %s pallet=%s model=%s",
                body.job_type, body.status, body.pallet_no, body.model)
    return seq