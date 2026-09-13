from fastapi import APIRouter
from src.services.master import proc_master_service
from src.schemas import response_schema
from src.schemas.master import proc_master_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("api")


# --------------------------------------------------------
# 공정 순서 관리 page
#   공정은 ERP 지시 수신 시 자동 등록된다.
#   여기서 정한 순서대로 피킹리스트가 발행된다.
# --------------------------------------------------------
@router.get("/get/all/proc/model/list")
def proc_model_list():
    """모델 목록. 좌측 트리."""
    result = proc_master_service.get_model_list()
    return response_schema.response(True, "모델 조회 성공", result)


@router.get("/get/proc/master/list")
def proc_list(model: str):
    """모델의 공정 목록. 순서대로."""
    try:
        result = proc_master_service.get_proc_list(model)
    except ValueError as e:
        return response_schema.response(False, str(e), None)
    if not result["items"]:
        return response_schema.response(False, "등록된 공정이 없습니다", result)
    return response_schema.response(True, "공정 조회 성공", result)


@router.post("/update/proc/master/order")
def update_proc_order(body: proc_master_schema.ProcOrderUpdate):
    """[순서 변경] — 드래그 결과 일괄 저장."""
    try:
        result = proc_master_service.update_order(
            body.model, [i.model_dump() for i in body.items], body.worker_id)
    except ValueError as e:
        logger.warning("[proc] 순서 변경 차단: %s", e)
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "공정 순서 변경 완료", result)