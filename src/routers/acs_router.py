from fastapi import APIRouter
from pydantic import BaseModel

from src.services import acs_status_service
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("api.acs")


class UpdateCallStatus(BaseModel):
    lpn_code: str
    status: str


# --------------------------------------------------------
# ACS -> WMS
#   ACS 가 AMR 진행 상황을 알려준다. WMS 는 받아서 K-LPN 상태에 반영한다.
#   응답 형식은 ACS 규격을 따른다 ({"flag": ...}). 우리 response_schema 와 다르다.
# --------------------------------------------------------
@router.post("/acs/update_call_status")
def update_call_status(body: UpdateCallStatus):
    """[2-1] 호출 정보 업데이트."""
    try:
        acs_status_service.update_call_status(body.lpn_code, body.status)
    except ValueError as e:
        logger.warning("상태 반영 거부 - %s %s (%s)", body.lpn_code, body.status, e)
        return {"flag": False, "msg": str(e)}
    except Exception as e:
        logger.exception("상태 반영 실패 - %s %s", body.lpn_code, body.status)
        return {"flag": False, "msg": f"처리 중 오류: {e}"}

    return {"flag": True}
