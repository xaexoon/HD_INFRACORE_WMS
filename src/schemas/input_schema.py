from typing import Optional
from pydantic import BaseModel, Field

class InsertRLpnItem(BaseModel):
    item_code: str = Field(..., max_length=30)
    init_qty:  int = Field(..., gt=0)


class InsertRLpn(BaseModel):
    """R LPN 등록 요청.

    자재 1종이면 items 에 한 건만 담는다.
    2종 이상이면 Multi-SKU 팔레트가 되며,
    mixed_allow = 1 이고 kitting_grp 가 같아야 한다.
    """
    items:     list[InsertRLpnItem] = Field(..., min_length=1)
    worker_id: Optional[str] = None
#
# class UpdateRLpn(BaseModel):
#     seq: int
#     init_qty: Optional[int] = Field(None, gt=0)
#     current_qty: Optional[int] = Field(None, ge=0)
#     location_seq: Optional[int] = None
#     reason: Optional[str] = Field(None, max_length=200)


class UpdateRLpnItem(BaseModel):
    detail_seq:  int
    init_qty:    Optional[int] = None
    current_qty: Optional[int] = None


class UpdateRLpn(BaseModel):
    seq:          int
    items:        list[UpdateRLpnItem] = []
    location_seq: Optional[int] = None
    reason:       Optional[str] = None
    worker_id:    Optional[str] = None

class MergePallet(BaseModel):
    source_code: str
    target_code: str
    device_id:   str | None = None
    worker_id:   str | None = None


class MergeItems(BaseModel):
    lpn_master_seq: int
    item_code:      str
    qty:            int
    device_id:      str | None = None
    worker_id:      str | None = None