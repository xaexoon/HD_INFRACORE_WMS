from fastapi import APIRouter
from src.schemas import response_schema, input_schema
from src.services import input_service
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("api.input")

@router.get("/get/all/r/lpn")
def get_all_r_lpn():
    return {"success": True, "msg": "전체 LPN 리스트 조회", "data": input_service.get_all_r_lpn()}

@router.get("/get/r/lpn/{lpn_code}")
def get_r_lpn_by_code(lpn_code: str):
    result = input_service.get_r_lpn_by_code(lpn_code)
    if not result:
        return response_schema.response(False, f"LPN 없음: {lpn_code}", None)
    return response_schema.response(True, "조회 성공", result)

@router.get("/get/{item_code}")
def get_r_lpn_by_item_code(item_code: str):
    result = input_service.get_r_lpn_by_item_code(item_code)
    if not result:
        return response_schema.response(False, f"등록된 ITEM_CODE 없음 : {item_code}", None)
    return response_schema.response(True, "조회 성공", result)

# R LPN 등록
@router.post("/insert/r/lpn")
def insert_r_lpn(body: input_schema.InsertRLpn):
    try:
        result = input_service.insert_r_lpn(body)
        return response_schema.response(True, "LPN 등록 완료", result)
    except ValueError as e:
        return response_schema.response(False, str(e), None)

# R LPN 발행
@router.get("/r/lpn/print/{lpn_master_seq}")
def print_r_lpn(lpn_master_seq: int, worker_id: str | None = None):
    try:
        result = input_service.print_r_lpn(lpn_master_seq, worker_id)
    except ValueError as e:
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "R LPN 출력 완료", result)

# 가용자재 전환 (랙, 자재 바인딩)
@router.post("/bind/r/lpn")
def bind_r_lpn(r_lpn_seq: int, location_seq: int,
               device_id: str | None = None,
               worker_id: str | None = None):
    try:
        result = input_service.bind_r_lpn(r_lpn_seq, location_seq, device_id, worker_id)
    except ValueError as e:
        logger.warning(f"바인딩 거부: lpn={r_lpn_seq} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "R LPN 바인딩 완료", result)


@router.post("/update/r/lpn")
def update_r_lpn(body: input_schema.UpdateRLpn):
    try:
        result = input_service.update_r_lpn(body)
    except ValueError as e:
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "LPN 수정 완료", result)


@router.get("/get/lpn/merge/preview/{lpn_code}")
def merge_preview(lpn_code: str):
    """통합 전 LPN 내용 확인."""
    result = input_service.get_merge_preview(lpn_code)
    if not result:
        return response_schema.response(False, "등록되지 않은 LPN 입니다", None)
    return response_schema.response(True, "LPN 조회 성공", result)


# 팔렛 통합
@router.post("/merge/pallet")
def merge_pallet(body: input_schema.MergePallet):
    """[팔레트 통합] — 소스 LPN 을 타겟으로 합치고 소스는 소멸."""
    logger.info("팔레트 통합 요청: %s", body.model_dump())
    try:
        result = input_service.merge_pallet(
            body.source_code, body.target_code, body.device_id, body.worker_id)
    except ValueError as e:
        logger.warning("통합 차단: %s", e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "팔레트 통합 완료", result)

@router.post("/merge/items")
def merge_items(body: input_schema.MergeItems):
    """[물리적 통합 입고] — 기존 R-LPN 에 수량 합산."""
    logger.info("통합 입고 요청: %s", body.model_dump())
    try:
        result = input_service.merge_items(
            body.lpn_master_seq, body.item_code, body.qty,
            body.device_id, body.worker_id)
    except ValueError as e:
        logger.warning("통합 입고 차단: %s", e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "통합 입고 완료", result)




