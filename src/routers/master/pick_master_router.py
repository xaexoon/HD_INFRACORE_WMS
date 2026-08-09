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


@router.post("/confirm/pick/master/list")
def confirm_pick(body: pick_master_schema.PickConfirm):
    """[확정] — kit_table 생성 + W/D-LPN 선발행."""
    logger.info("[pick] 확정 요청: %s", body.model_dump())
    try:
        result = pick_master_service.confirm(body.order_no, body.vornr, body.worker_id)
    except ValueError as e:
        logger.warning("[pick] 확정 차단: order=%s proc=%s reason=%s",
                       body.order_no, body.vornr, e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "피킹 확정 완료", result)


# 피킹리스트 분할
@router.post("/split/pick/master")
def split_pick():
    return None

# 피킹리스트 통합