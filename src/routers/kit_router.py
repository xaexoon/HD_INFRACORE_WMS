from fastapi import APIRouter
from src.services import kit_service
from src.schemas import response_schema, kit_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("api.kit")


# --------------------------------------------------------
# 키팅 공정 page
#   W/D-LPN 바인딩 완료 → 키팅 지시 발행 → 태블릿 작업 목록
# --------------------------------------------------------
@router.get("/get/all/kit/wait/list")
def kit_wait_list():
    """발행 대기 목록. ready_yn = 1 인 건만 발행 가능."""
    result = kit_service.get_wait_list()
    if not result :
        return response_schema.response(False, "키팅 발행 대기 목록이 없습니다", None)
    return response_schema.response(True, "키팅 발행 대기 목록", result)


@router.get("/get/all/kit/list")
def kit_issued_list():
    """태블릿 키팅 작업 목록. 발행된 건만."""
    result = kit_service.get_issued_list()
    return response_schema.response(True, "키팅 작업 목록", result)


@router.get("/get/kit/{kit_seq}")
def kit_items(kit_seq: int):
    """키팅 1건 상세 — 담긴 자재 목록."""
    result = kit_service.get_kit_items(kit_seq)
    if not result:
        return response_schema.response(False, "자재가 없습니다", None)
    return response_schema.response(True, "키팅 상세 조회", result)


@router.post("/issue/kit")
def issue_kit(body: kit_schema.IssueKit):
    """[키팅 리스트 발행] — WAIT → ISSUED."""
    try:
        result = kit_service.issue_kit(body.kit_seq, body.worker_id)
    except ValueError as e:
        logger.warning(f"발행 거부: kit={body.kit_seq} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "키팅 지시 발행 완료", result)


@router.post("/cancel/kit/issue/{kit_seq}")
def cancel_issue(kit_seq: int, worker_id: str | None = None):
    """발행 취소 — 키팅 착수 전에만."""
    try:
        result = kit_service.cancel_issue(kit_seq, worker_id)
    except ValueError as e:
        logger.warning(f"발행 취소 거부: kit={kit_seq} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "발행 취소 완료", result)

@router.post("/verify/kit")
def verify_kit(body: kit_schema.VerifyKit):
    """[3중 검증] — W/D-LPN 스캔. 전량 PASS 시 K-LPN 자동 생성."""
    try:
        result = kit_service.verify_kit(
            body.kit_seq, body.lpn_code, body.device_id, body.worker_id)
    except ValueError as e:
        logger.warning(f"검증 거부: kit={body.kit_seq} - {e}")
        return response_schema.response(False, str(e), None)

    if result["result"] == "FAIL":
        return response_schema.response(False, result["fail_reason"], result)

    msg = "키팅 완료" if result["k_lpn"] else "검증 PASS"
    return response_schema.response(True, msg, result)


@router.get("/get/kit/verify/log/{kit_seq}")
def verify_log(kit_seq: int):
    """3중 검증 이력 조회."""
    result = kit_service.get_verify_log(kit_seq)
    return response_schema.response(True, "검증 이력 조회", result)

# @router.post("/insert/kit/k/lpn")
# def insert_k_lpn(body: kit_schema.InsertKLpn):
#     """[K-LPN 생성] — 3중 검증 PASS 후 W/D-LPN 통합."""
#     try:
#         result = kit_service.insert_k_lpn(
#             body.kit_seq, body.device_id, body.worker_id)
#     except ValueError as e:
#         logger.warning(f"K-LPN 생성 거부: kit={body.kit_seq} - {e}")
#         return response_schema.response(False, str(e), None)
#     return response_schema.response(True, "K-LPN 생성 완료", result)