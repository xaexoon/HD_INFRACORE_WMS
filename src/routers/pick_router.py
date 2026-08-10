from fastapi import APIRouter
from src.services import pick_service
from src.schemas import response_schema, pick_schema
from src.logger.logger import get_logger

router = APIRouter()

@router.get("/get/all/pick/list")
def get_all_pick_list():
    result = pick_service.get_pick_list_grp_kit()
    return response_schema.response(True, "확정된 피킹 리스트 전체 조회", result)

# @router.get("/get/all/pick/grp/kit")
# def get_pick_list_grp_kit():
#     result = pick_service.get_pick_list_grp_kit()
#     return response_schema.response(True, "피킹 리스트 전체 조회", result)

@router.get("/get/pick/{seq}")
def get_pick_by_seq(seq:int):
    result = pick_service.get_pick_by_seq(seq)
    return response_schema.response(True, "확정된 단일 피킹리스트 조회", result)


# 라벨 선발행 (W-LPN)
# pick_router.py
@router.post("/insert/w-lpn/{kit_seq}")
def insert_w_lpn(kit_seq: int):
    try:
        data = pick_service.issue_w_lpn(kit_seq)
        return response_schema.response(True, "W-LPN 발행 완료", data)
    except Exception as e:
        logger.error(f"W-LPN 발행 실패 - {e}")
        return response_schema.response(False, str(e), None)

@router.post("/insert/d-lpn/{kit_seq}")
def insert_d_lpn(kit_seq: int):
    try:
        data = pick_service.issue_d_lpn(kit_seq)
        return response_schema.response(True, "D-LPN 발행 완료", data)
    except Exception as e:
        logger.error(f"D-LPN 발행 실패 - {e}")
        return response_schema.response(False, str(e), None)

# 바인딩 (W-LPN)
@router.get("/bind/w/lpn")
def bind_w_lpn():
    return response_schema.response(True, "W LPN 바인딩 완료", None)

# 바인딩 (D-LPN)
@router.get("/bind/d/lpn")
def bind_d_lpn():
    return response_schema.response(True, "D LPN 바인딩 완료", None)

# 세척 대기존 이동 후 스캔
@router.get("/buffer/wait/w/lpn")
def buffer_wait_w_lpn(w_lpn_seq: int):
    return None

# 하향 (재고 차감 + 우선 순위 할당)
@router.get("/lift/down/r/lpn")
def lift_down_r_lpn():

    # 자재 수량 차감

    # 수량 차감 후 잔재가 남을 시 우선 순위 할당

    # 상태 변경 (하향 중)

    return None