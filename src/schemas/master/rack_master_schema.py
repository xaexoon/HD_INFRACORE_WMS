from typing import Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class RackInsert(BaseModel):
    """랙 등록 요청"""
    rack_code: str = Field(..., min_length=1, max_length=30, description="랙 코드")
    rack_name: Optional[str] = Field(None, max_length=200, description="랙 이름")
    zone_seq: int = Field(..., description="소속 구역 seq")
    rows: Optional[int] = Field(None, ge=1, le=99, description="세로 단수")
    cols: Optional[int] = Field(None, ge=1, le=99, description="가로 열수")

    @field_validator("rack_code")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().upper()


class RackUpdate(BaseModel):
    """랙 수정 요청 — 전체 필드 수정"""
    seq: int
    rack_code: str = Field(..., min_length=1, max_length=30, description="랙 코드")
    rack_name: Optional[str] = Field(None, max_length=200, description="랙 이름")
    zone_seq: int = Field(..., description="소속 구역 seq")
    rows: Optional[int] = Field(None, ge=1, le=99, description="세로 단수")
    cols: Optional[int] = Field(None, ge=1, le=99, description="가로 열수")
    enable_yn: bool = Field(True, description="사용 여부")

    @field_validator("rack_code")
    @classmethod
    def normalize(cls, v: str) -> str:
        return v.strip().upper()


class RackDelete(BaseModel):
    """랙 삭제 요청"""
    seq: int