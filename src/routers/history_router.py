from fastapi import APIRouter
from src.services import history_service
from src.schemas import response_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("History Router")


# --------------------------------------------------------
# 이력 조회 page
#   기본 : 오늘 / 전체 유형
# --------------------------------------------------------
@router.get("/get/history/list")
def history_list(date_from: str | None = None,
                 date_to: str | None = None,
                 txn_type: str | None = None,
                 lpn_type: str | None = None,
                 keyword: str = ""):
    result = history_service.get_txn_list(date_from, date_to, txn_type, keyword, lpn_type)
    return response_schema.response(True, "이력 조회 성공", result)


@router.get("/get/history/lpn/{lpn_code}")
def lpn_history(lpn_code: str):
    """LPN 추적 — 입고부터 소진까지."""
    result = history_service.get_lpn_history(lpn_code)
    if not result:
        return response_schema.response(False, "해당 LPN 이력이 없습니다", None)
    return response_schema.response(True, "LPN 이력 조회 성공", result)


@router.get("/get/history/item/{item_code}")
def item_history(item_code: str,
                 date_from: str | None = None,
                 date_to: str | None = None):
    """자재 추적 — 어느 엔진/공정에 투입됐나."""
    result = history_service.get_item_history(item_code, date_from, date_to)
    return response_schema.response(True, "자재 이력 조회 성공", result)


@router.get("/get/history/types")
def txn_types():
    """유형 셀렉트박스용."""
    result = history_service.get_txn_types()
    return response_schema.response(True, "유형 목록 조회 성공", result)


@router.get("/get/history/{seq}")
def history_detail(seq: int):
    """이력 단건 상세."""
    result = history_service.get_txn_by_seq(seq)
    if not result:
        return response_schema.response(False, "해당 이력이 없습니다", None)
    return response_schema.response(True, "이력 상세 조회 성공", result)


@router.get("/get/history/pick/{pick_seq}")
def pick_history(pick_seq: int):
    """같은 피킹 지시로 묶인 거래 목록."""
    result = history_service.get_txn_by_pick(pick_seq)
    return response_schema.response(True, "피킹 이력 조회 성공", result)