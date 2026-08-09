from typing import Optional
from pydantic import BaseModel, Field


class InsertRLpn(BaseModel):
    """R LPN 등록 요청 — 클라이언트가 실제로 보내는 값만"""
    item_code: str = Field(..., max_length=30)
    init_qty: int = Field(..., gt=0)
    location_seq: Optional[int] = None

class IntegrateRLpn(BaseModel):
    seq:int
    item_code:str
    init_qty:int


class UpdateRLpn(BaseModel):
    seq: int
    init_qty: Optional[int] = Field(None, gt=0)
    current_qty: Optional[int] = Field(None, ge=0)
    location_seq: Optional[int] = None
    reason: Optional[str] = Field(None, max_length=200)