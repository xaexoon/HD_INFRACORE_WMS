from fastapi import APIRouter
from src.schemas import response_schema, input_schema
from src.services import input_service
router = APIRouter()


@router.get("/get/all/r/lpn")
def get_all_r_lpn():
    return {"success": True, "msg": "전체 LPN 리스트 조회", "data": input_service.get_all_r_lpn()}

@router.get("/get/r/lpn/{lpn_code}")
def get_r_lpn_by_code(lpn_code:str):
    result = input_service.get_r_lpn_by_code(lpn_code)
    if not result:
        raise HTTPException(404, f"LPN 없음: {lpn_code}")
    return {"success": True, "msg": "조회 성공", "data": result}

# R LPN 등록
@router.post("/insert/r/lpn")
def insert_r_lpn(body: input_schema.InsertRLpn):
    try:
        result = input_service.insert_r_lpn(body)
        return response_schema.response(True, "LPN 등록 완료", result)
    except ValueError as e:
        return response_schema.response(False, str(e), None)

# R LPN 발행
@router.get("/r-lpn/print/{lpn_master_seq}")
def print_r_lpn(lpn_master_seq: int):
    result= input_service.print_r_lpn(lpn_master_seq)
    return response_schema.response(True, "LPN 발행 완료", result)

# 가용자재 전환 (랙, 자재 바인딩)
@router.get("/bind/r/lpn")
def bind_r_lpn(r_lpn_seq: int, location_seq: int ):
    result = input_service.bind_r_lpn(r_lpn_seq, location_seq)
    return response_schema.response(True, "LPN 적재 완료", result)

# R LPN 수정
@router.post("/update/r/lpn")
def update_r_lpn(body: input_schema.UpdateRLpn):
    result = input_service.update_r_lpn(body)
    return response_schema.response(True, "LPN 수정 완료", result)

# 물리적 통합
@router.get("/integrate/insert")
def integrate_insert(r_lpn_seq: int):

    # R LPN 데이터 조회

    # 위 데이터 수량 추가

    return None

# 팔렛 통합
@router.get("/integrate/pallet")
def integrate_pallet(source_seq: int, target_seq: int):

    # 소스 자재 수량 차감

    # 타켓 자재 수량 추가
    return None


