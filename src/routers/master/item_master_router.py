from fastapi import APIRouter
from src.schemas import item_schema, response_schema
from src.services.master import item_master_service

router = APIRouter()


@router.get("/get/items/master")
def get_item_master_list(keyword:str):
    if keyword:
        result = item_master_service.search_item_master(keyword)
    else:
        result = item_master_service.get_item_master_list()
    return response_schema.response(True, "자재 조회 완료", result)


@router.get("/get/item/master")
def get_item_master(item_seq: int):
    result = item_master_service.get_item_master(item_seq)
    if result is None:
        return response_schema.response(False, "자재를 찾을 수 없습니다", None)
    return response_schema.response(True, "자재 조회 완료", result)


@router.post("/insert/item/master")
def insert_item_master(body: item_schema.ItemInsert):
    seq = item_master_service.insert_item_master(body)
    return response_schema.response(True, "자재 등록 완료", {"seq": seq})


@router.post("/update/item/master")
def update_item_master(body: item_schema.ItemUpdate):
    affected = item_master_service.update_item_master(body)
    if affected == 0:
        return response_schema.response(False, "수정할 자재가 없습니다", None)
    return response_schema.response(True, "자재 수정 완료", None)


@router.post("/delete/item/master")
def delete_item_master(item_seq: int):
    affected = item_master_service.delete_item_master(item_seq)
    if affected == 0:
        return response_schema.response(False, "삭제할 자재가 없습니다", None)
    return response_schema.response(True, "자재 삭제 완료", None)