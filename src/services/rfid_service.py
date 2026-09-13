from datetime import date

from src.db.connection import execute, query
from src.queries import lpn_query
from src.logger.logger import get_logger

logger = get_logger("svc.rfid")


def get_k_lpn_rfid_list(target_date: str | None = None) -> list[dict]:
    day = target_date or date.today().isoformat()
    return query(lpn_query.SELECT_K_LPN_FOR_RFID, (day, day))


def rfid_write(lpn_code: str) -> int:
    affected = execute(lpn_query.RFID_WRITE, (lpn_code.strip().upper(),))
    if affected:
        logger.info("RFID 기록 %s", lpn_code)
    return affected