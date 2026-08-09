# from datetime import datetime
#
#
from fastapi import APIRouter
# from pydantic import BaseModel
#
# from src.services import api_service
# from fastapi import HTTPException
router = APIRouter()
#
# # qr api
#
# class GrLpnInsert(BaseModel):
#     item_code: str
#     received_qty: int
#     received_date: str
#     device_id : str
#     worker_id : str
#
# @router.get("/qr/items/search")
# def qr_item_search(keyword: str = ""):
#     if keyword:
#         data = api_service.search_items(keyword)
#     else:
#         data = api_service.get_all_items()
#     return {"success": True, "msg": "자재 리스트 조회", "data": data}
#
# @router.get("/qr/items/{item_code}")
# def qr_item_by_item_code(item_code:str):
#     return {"success": True, "msg": f"{item_code} 상세 조회", "data": api_service.search_items(item_code)}
#
# # 입고 등록
# @router.post("/qr/gr/insert/lpn")
# def qr_gr_lpn_insert(insertModel: GrLpnInsert):
#     try:
#
#         lpn_code = api_service.make_lpn_code()
#         if (lpn_code is None or lpn_code == ""):
#             return {"success" : False, "msg" : "LPN 코드 생성 실패", "data":None}
#
#         result= api_service.insert_gr_lpn(
#             item_code = insertModel.item_code,
#             received_qty = insertModel.received_qty,
#             received_date = insertModel.received_date,
#             device_id = insertModel.device_id,
#             worker_id = insertModel.worker_id,
#             lpn_code = lpn_code
#         )
#     except ValueError as e :
#         raise HTTPException(400, str(e))
#
#
#
#
#
# # 라벨 발행
# @router.get("/qr/gr/lpn/print/{lpn_code}")
# def qr_gr_lpn_print(lpn_code: str):
#     try:
#         api_service.update_to_print(lpn_code)
#     except Exception as e :
#         raise HTTPException(400, str(e))
#     return {"success" : True, "msg" : "LPN 발행 완료", 'data' : None}
#
#
#
#
#
#
#
#
# @router.get("/all/lpn")
# def get_all_lpn():
#     return {"success" : True, "msg": "전체 LPN 리스트 조회", "data": api_service.get_all_lpn()}
#
#
#
# @router.get("/lpn/{lpn_code}")
# def get_lpn(lpn_code: str):
#     result = api_service.get_lpn(lpn_code)
#     if not result:
#         raise HTTPException(404, f"LPN 없음: {lpn_code}")
#     return {"success": True, "msg": "조회 성공", "data": result}