# -*- coding: utf-8 -*-
"""
공통 API 응답 스키마
---------------------
모든 엔드포인트가 {success, msg, data} 형태로 응답하도록 통일한다.
라우터에서 response_model 로 지정하면 /docs 에 응답 형태까지 문서화된다.

사용:
    @router.get("", response_model=ApiResponse[list[ItemResponse]])
    def list_items(keyword: str = ""):
        return response(data=item_service.search(keyword), msg="자재 리스트 조회")
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """공통 응답 래퍼.

    success : 처리 성공 여부
    msg     : 화면에 띄울 메시지
    data    : 실제 payload. 없으면 None
    """

    success: bool = True
    msg: str = ""
    data: Optional[T] = None


def response(
    success: bool = True,
    msg: str = "",
    data: Optional[T] = None,
) -> ApiResponse[T]:
    """공통 응답 생성.

    성공 : response(True, "조회 완료", 목록)
    실패 : response(False, "자재를 찾을 수 없습니다")
    """
    return ApiResponse(success=success, msg=msg, data=data)