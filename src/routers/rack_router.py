
from fastapi import APIRouter
from src.services import rack_service
from src.schemas import response_schema

router = APIRouter()


# --------------------------------------------------------
# 랙 적재 현황 조회 page
#   좌측 : 구역 격자   /   우측 : 셀 상세
#   마스터 관리(랙 등록/수정)는 rack_master 에서 담당
# --------------------------------------------------------
@router.get("/get/zone/list")
def zone_list():
    """랙 위치(구역) 셀렉트박스용 전체 목록."""
    result = rack_service.get_zones()
    return response_schema.response(True, "구역 목록 조회 성공", result)

@router.get("/get/zone/grid/{zone_seq}")
def zone_grid(zone_seq: int, rack_seq: int | None = None):
    """구역 내 랙별 격자. rack_seq 를 주면 해당 랙만."""
    result = rack_service.get_zone_grid(zone_seq, rack_seq)
    if not result:
        return response_schema.response(False, "해당 구역에 랙이 없습니다", None)
    return response_schema.response(True, "격자 조회 성공", result)


@router.get("/get/cell/{location_seq}")
def cell_detail(location_seq: int):
    """셀 클릭 시 적치된 LPN / 자재 조회."""
    result = rack_service.get_cell_detail(location_seq)
    return response_schema.response(True, "셀 조회 성공", result)