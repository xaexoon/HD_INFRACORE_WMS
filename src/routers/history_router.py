from fastapi import APIRouter
from src.services import history_service
from src.schemas import response_schema
from src.logger.logger import get_logger
from src.services.history_service import get_kit_history

router = APIRouter()
logger = get_logger("api.history")


# --------------------------------------------------------
# 이력 조회 page
#   기본 : 오늘 / 전체 유형
# --------------------------------------------------------
@router.get("/get/history/list")
def history_list(date_from: str | None = None,
                 date_to: str | None = None,
                 txn_type: str | None = None,
                 lpn_type: str | None = None,
                 zone_code: str | None = None,
                 doc_no: str | None = None,
                 location: str | None = None,
                 keyword: str = ""):
    """이력 조회. 필터 6종 조합 가능."""
    result = history_service.get_txn_list(
        date_from, date_to, txn_type, lpn_type,
        zone_code, doc_no, location, keyword)
    return response_schema.response(True, "이력 조회 성공", result)


@router.get("/get/history/lpn-types")
def lpn_types():
    """LPN 유형 셀렉트박스용."""
    return response_schema.response(True, "LPN 유형 조회 성공",
                                    history_service.get_lpn_types())


@router.get("/get/history/zones")
def zones():
    """구역 셀렉트박스용."""
    return response_schema.response(True, "구역 조회 성공",
                                    history_service.get_zones())


@router.get("/get/history/low/items")
def low_stock(threshold: int = 10):
    """저재고 자재 조회."""
    return response_schema.response(True, "저재고 조회 성공",
                                    history_service.get_low_stock(threshold))

@router.get("/get/history/lpn/detail/{lpn_code}")
def history_lpn_detail(lpn_code: str):
    """LPN 상세 — 현재 상태 · 담긴 자재 · 전체 이력."""
    result = history_service.get_history_lpn(lpn_code)
    if not result:
        return response_schema.response(False, "등록되지 않은 LPN 입니다", None)
    return response_schema.response(True, "LPN 상세 조회 성공", result)


@router.get("/get/history/pick/list")
def pick_history(date_from: str | None = None,
                 date_to: str | None = None,
                 status: str | None = None,
                 pick_no: str | None = None,
                 keyword: str = ""):
    """피킹리스트 이력. 1행 = [오더 + 공정] 단위."""
    result = history_service.get_pick_history(
        date_from, date_to, status, pick_no, keyword)
    return response_schema.response(True, "피킹리스트 이력 조회 성공", result)


@router.get("/get/history/pick/items/{pick_no}")
def pick_history_items(pick_no: str):
    """피킹리스트 1건 상세 — 헤더 + W/D 자재."""
    result = history_service.get_pick_history_items(pick_no)
    if not result:
        return response_schema.response(False, "해당 피킹 지시가 없습니다", None)
    return response_schema.response(True, "상세 조회 성공", result)

@router.get("/get/history/kit/list")
def kit_history(date_from: str | None = None,
                date_to: str | None = None,
                status: str | None = None,
                kit_no: str | None = None,
                keyword: str = ""):
    """키팅리스트 이력. W/D/K-LPN 과 검증 결과 포함."""
    result = history_service.get_kit_history(
        date_from, date_to, status, kit_no, keyword)
    return response_schema.response(True, "키팅리스트 이력 조회 성공", result)

@router.get("/get/history/kit/items/{kit_no}")
def kit_history_items(kit_no: str):
    """키팅리스트 1건 상세 — LPN · 자재 · 검증 이력."""
    result = history_service.get_kit_history_items(kit_no)
    if not result:
        return response_schema.response(False, "해당 키팅이 없습니다", None)
    return response_schema.response(True, "상세 조회 성공", result)
