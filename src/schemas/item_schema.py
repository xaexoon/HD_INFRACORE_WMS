from typing import Optional
from pydantic import BaseModel, Field, field_validator

class ItemInsert(BaseModel):
    """자재 등록 요청"""
    item_code: str = Field(..., min_length=1, max_length=30, description="자재 코드")
    item_name: str = Field(..., max_length=30, description="자재명")
    uom: str = Field(..., max_length=10, description="수량 단위")
    washing_yn: bool = Field(False, description="세척 필요 여부")
    catch_weight_yn: bool = Field(False, description="실중량 관리 여부")
    mixed_allow: bool = Field(False, description="혼적 허용 여부")
    kitting_grp: Optional[str] = Field(None, max_length=20, description="키팅 그룹")

    @field_validator("item_code", "uom")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().upper()

class ItemUpdate(BaseModel):
    """자재 수정 요청 — 보낸 필드만 반영"""
    seq: int
    item_name: Optional[str] = Field(None, max_length=30)
    uom: Optional[str] = Field(None, max_length=10)
    washing_yn: Optional[bool] = None
    catch_weight_yn: Optional[bool] = None
    mixed_allow: Optional[bool] = None
    kitting_grp: Optional[str] = Field(None, max_length=20)
