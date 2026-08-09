from fastapi import APIRouter
from src.services.master import rack_master_service
from src.schemas.master import rack_master_schema
from src.schemas import response_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("Rack Master Router")

# --------------------------------------------------------
# rack 관리 page
#   적치 현황(LPN/자재) 조회는 rack_status 에서 담당
# --------------------------------------------------------
@router.get("/get/all/rack/master")
def rack_search(keyword: str = ""):

    if keyword:
        result = rack_service.get_racks_by_search(keyword)
        msg = "키워드 검색 성공"
    else:
        result = rack_master_service.get_all_racks()
        msg = "전체 조회 성공"
    return response_schema.response(True, msg, result)


@router.get("/get/rack/master/{seq}")
def rack_seq(seq: int):
    result = rack_master_service.get_rack_by_seq(seq)
    if not result:
        return response_schema.response(False, "해당 랙이 없습니다", None)
    return response_schema.response(True, "상세 조회 성공", result)



@router.post("/insert/rack/master")
def insert_rack_master(body: rack_master_schema.RackInsert):
    if rack_master_service.exists_rack_code(body.rack_code):
        return response_schema.response(False, "이미 사용 중인 랙코드입니다", None)
    logger.info(f"[rack_master] 추가 할 랙 정보 : {body}")
    rack_master_service.insert_rack_master(body)
    return response_schema.response(True, "랙 등록 완료", None)


@router.post("/update/rack/master")
def update_rack_master(body: rack_master_schema.RackUpdate):
    if rack_master_service.exists_rack_code(body.rack_code, except_seq=body.seq):
        return response_schema.response(False, "이미 사용 중인 랙코드입니다", None)
    if rack_master_service.update_rack_master(body) == 0:
        return response_schema.response(False, "수정할 랙이 없습니다", None)
    return response_schema.response(True, "랙 수정 완료", None)


@router.post("/disable/rack/master")
def disable_rack_master(body: rack_master_schema.RackDelete):
    """사용중지. 이력이 남아 있으므로 삭제보다 이쪽이 기본."""
    if rack_master_service.disable_rack_master(body.seq) == 0:
        return response_schema.response(False, "해당 랙이 없습니다", None)
    return response_schema.response(True, "랙 사용중지 완료", None)


@router.post("/delete/rack/master")
def delete_rack_master(body: rack_master_schema.RackDelete):
    location_cnt = rack_master_service.count_locations(body.seq)
    if location_cnt:
        return response_schema.response(
            False, f"하위 로케이션 {location_cnt}건이 있어 삭제할 수 없습니다", None
        )
    if rack_master_service.delete_rack_master(body.seq) == 0:
        return response_schema.response(False, "삭제할 랙이 없습니다", None)
    return response_schema.response(True, "랙 삭제 완료", None)