from fastapi import APIRouter
from src.services.master import pick_master_service
from src.schemas import response_schema, pick_schema
from src.schemas.master import pick_master_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("Pick Router")


# --------------------------------------------------------
# 피킹 리스트 관리 page
#   1행 = [호기 + 공정] 단위의 피킹 JOB
#   확정 시 kit_table 생성 + W/D-LPN 선발행 + pick_table ISSUED
# --------------------------------------------------------
@router.get("/get/all/pick/master/list")
def pick_list():
    """확정 대기(WAIT) 목록."""
    result = pick_master_service.get_wait_list()
    return response_schema.response(True, "피킹리스트 조회 성공", result)


@router.get("/get/pick/master/items")
def pick_items(order_no: str, vornr: str):
    """[보기] — 해당 공정의 하위 자재 목록."""
    result = pick_master_service.get_items(order_no, vornr)
    if not result["items"]:
        return response_schema.response(False, "해당 공정의 자재가 없습니다", None)
    return response_schema.response(True, "하위 자재 조회 성공", result)

@router.get("/get/pick/master/check")
def pick_check(order_no: str, vornr: str):
    """[확정 가능 여부] — 버튼 활성화 판단용."""
    invalid  = pick_master_service.get_invalid(order_no, vornr)
    shortage = pick_master_service.check_stock(order_no, vornr)
    return response_schema.response(True, "확정 검증 완료", {
        "can_confirm":   not invalid and not shortage,
        "invalid_items": invalid,
        "short_items":   shortage,
    })


@router.post("/confirm/pick/master/list")
def confirm_pick(body: pick_master_schema.PickConfirm):
    """[확정] — kit_table 생성 + R-LPN 할당(PLAN) + pick_table ISSUED."""
    logger.info("[pick] 확정 요청: %s", body.model_dump())
    try:
        result = pick_master_service.confirm(body.order_no, body.vornr, body.worker_id)
    except ValueError as e:
        logger.warning("[pick] 확정 차단: order=%s proc=%s reason=%s",
                       body.order_no, body.vornr, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "피킹 확정 완료", result)


@router.post("/cancel/pick/master/{kit_seq}")
def cancel_pick(kit_seq: int, worker_id: str):
    """[확정 취소] — 피킹 시작 전에만 가능."""
    try:
        result = pick_master_service.cancel(kit_seq, worker_id)
    except ValueError as e:
        logger.warning("[pick] 취소 차단: kit=%s reason=%s", kit_seq, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "확정 취소 완료", result)