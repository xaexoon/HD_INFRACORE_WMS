
from fastapi import APIRouter, Body
from src.services import rfid_service
router = APIRouter()
from src.schemas import response_schema


@router.get("/get/k-lpn/rfid/list")
def k_lpn_rfid_list(target_date: str | None = None):
    """핸디 RFID 앱용 K-LPN 목록. 미지정 시 오늘."""
    result = rfid_service.get_k_lpn_rfid_list(target_date)
    return response_schema.response(True, "K-LPN 목록 조회 성공", result)

@router.post("/rfid/write")
def rfid_write(lpn_code: str = Body(...)):
    affected = rfid_service.rfid_write(lpn_code)
    if affected == 0:
        return response_schema.response(False, "대상이 없거나 이미 기록된 LPN 입니다", None)
    return response_schema.response(True, "RFID Write 성공", None)