from fastapi import APIRouter
from src.services import kit_service
from src.schemas import response_schema, kit_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("Kit Router")


# --------------------------------------------------------
# 키팅 공정 page
#   W/D-LPN 바인딩 완료 → 키팅 지시 발행 → 태블릿 작업 목록
# --------------------------------------------------------
@router.get("/get/all/kit/wait/list")
def kit_wait_list():
    """발행 대기 목록. ready_yn = 1 인 건만 발행 가능."""
    result = kit_service.get_wait_list()
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
        logger.warning(f"[kit] 발행 거부: kit={body.kit_seq} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "키팅 지시 발행 완료", result)


@router.post("/cancel/kit/issue/{kit_seq}")
def cancel_issue(kit_seq: int, worker_id: str | None = None):
    """발행 취소 — 키팅 착수 전에만."""
    try:
        result = kit_service.cancel_issue(kit_seq, worker_id)
    except ValueError as e:
        logger.warning(f"[kit] 발행 취소 거부: kit={kit_seq} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "발행 취소 완료", result)