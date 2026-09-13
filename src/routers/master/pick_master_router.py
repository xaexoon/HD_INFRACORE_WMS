from fastapi import APIRouter
from src.services.master import pick_master_service
from src.schemas import response_schema, pick_schema
from src.schemas.master import pick_master_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("api.pickm")


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
def pick_items(pick_no):
    """[보기] — 해당 공정의 하위 자재 목록."""
    result = pick_master_service.get_items(pick_no)
    if not result["items"]:
        return response_schema.response(False, "해당 공정의 자재가 없습니다", None)
    return response_schema.response(True, "하위 자재 조회 성공", result)

# @router.get("/get/pick/master/check")
# def pick_check(order_no: str, vornr: str):
#     """[확정 가능 여부] — 버튼 활성화 판단용."""
#     invalid  = pick_master_service.get_invalid(order_no, vornr)
#     shortage = pick_master_service.check_stock(order_no, vornr)
#     return response_schema.response(True, "확정 검증 완료", {
#         "can_confirm":   not invalid and not shortage,
#         "invalid_items": invalid,
#         "short_items":   shortage,
#     })

@router.get("/get/pick/master/check")
def pick_check(pick_no: str):
    """[확정 가능 여부] — 버튼 활성화 판단용."""
    invalid  = pick_master_service.get_invalid(pick_no)
    shortage = pick_master_service.check_stock(pick_no)
    return response_schema.response(True, "확정 검증 완료", {
        "can_confirm":   not invalid and not shortage,
        "invalid_items": invalid,
        "short_items":   shortage,
    })


@router.post("/confirm/pick/master/list")
def confirm_pick(pick_no: str, worker_id: str | None = None):
    """[확정] — kit_table 생성 + R-LPN 할당(PLAN) + pick_table ISSUED."""
    logger.info("확정 요청: pick_no=%s", pick_no)
    try:
        result = pick_master_service.confirm(pick_no, worker_id)
    except ValueError as e:
        logger.warning("확정 차단: pick_no=%s reason=%s", pick_no, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "피킹 확정 완료", result)

@router.post("/cancel/pick/master/{kit_seq}")
def cancel_pick(kit_seq: int, worker_id: str | None = None):
    """[확정 취소] — 피킹 시작 전에만 가능."""
    try:
        result = pick_master_service.cancel(kit_seq, worker_id)
    except ValueError as e:
        logger.warning("취소 차단: kit=%s reason=%s", kit_seq, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "확정 취소 완료", result)

# --------------------------------------------------------
# 긴급 피킹
# --------------------------------------------------------
@router.get("/get/emergency/pick/list")
def emergency_pick_list():
    """긴급 피킹 대상 피킹리스트. 확정된 것만."""
    result = pick_master_service.get_emergency_pick_list()
    return response_schema.response(True, "긴급 피킹 대상 조회 성공", result)


@router.get("/get/emergency/pick/items/{kit_seq}")
def emergency_pick_items(kit_seq: int):
    """해당 피킹리스트의 자재 + 가용재고."""
    result = pick_master_service.get_emergency_pick_items(kit_seq)
    if not result:
        return response_schema.response(False, "해당 피킹리스트의 자재가 없습니다", None)
    return response_schema.response(True, "자재 조회 성공", result)


@router.post("/insert/emergency/pick")
def add_emergency_pick(body: pick_master_schema.EmergencyPick):
    """[긴급 피킹] — 기존 키팅에 자재 보충."""
    logger.info("긴급 피킹 요청: %s", body.model_dump())
    try:
        result = pick_master_service.add_emergency_pick(
            body.pick_seq, body.qty, body.reason, body.worker_id)
    except ValueError as e:
        logger.warning("긴급 피킹 차단: pick=%s reason=%s", body.pick_seq, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "긴급 피킹 지시 완료", result)

@router.post("/cancel/emergency/pick")
def cancel_emergency_pick(body: pick_master_schema.CancelEmergencyPick):
    """[긴급 피킹 취소] — 스캔 전에만 가능."""
    logger.info("긴급 피킹 취소 요청: %s", body.model_dump())
    try:
        result = pick_master_service.cancel_emergency_pick(
            body.pick_seq, body.reason, body.worker_id)
    except ValueError as e:
        logger.warning("긴급 취소 차단: pick=%s reason=%s", body.pick_seq, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "긴급 피킹 취소 완료", result)

# --------------------------------------------------------
# 수동 피킹리스트 등록
#   ERP 장애 시 현장 작업을 이어가기 위한 비상 수단
# --------------------------------------------------------
@router.get("/search/item")
def search_item(keyword: str):
    """자재 검색 — 수동 입력 자동완성용."""
    result = pick_master_service.search_items(keyword)
    return response_schema.response(True, "자재 검색 성공", result)


@router.post("/insert/manual/pick")
def add_manual_pick(body: pick_master_schema.ManualPick):
    """[수동 등록] — ERP 지시 없이 피킹리스트 생성."""
    logger.info("수동 등록 요청: %s", body.model_dump())
    try:
        result = pick_master_service.add_manual_pick(
            body.order_no, body.vornr, body.engine_no,
            [i.model_dump() for i in body.items],
            body.plan_date, body.engine_seq_no,
            body.arbpl, body.remark, body.worker_id)
    except ValueError as e:
        logger.warning("수동 등록 차단: %s", e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "수동 피킹리스트 등록 완료", result)

@router.post("/split/pick/master")
def split_pick(body: pick_master_schema.SplitPick):
    """[분할] — 확정 전 지시를 둘로 나눈다. 분할본은 공정 +1."""
    logger.info("분할 요청: %s", body.model_dump())
    try:
        result = pick_master_service.split_pick(
            body.pick_no, [i.model_dump() for i in body.items],
            body.reason, body.worker_id)
    except ValueError as e:
        logger.warning("분할 차단: pick_no=%s reason=%s", body.pick_no, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "피킹리스트 분할 완료", result)

@router.post("/cancel/split/pick/master")
def cancel_split_pick(body: pick_master_schema.CancelSplitPick):
    """[분할 취소] — 확정 전에만. 원본 수량을 복원한다."""
    logger.info("분할 취소 요청: %s", body.model_dump())
    try:
        result = pick_master_service.cancel_split_pick(
            body.pick_no, body.reason, body.worker_id)
    except ValueError as e:
        logger.warning("분할 취소 차단: pick_no=%s reason=%s", body.pick_no, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "분할 취소 완료", result)