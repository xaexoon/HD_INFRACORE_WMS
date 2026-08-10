from typing import Optional
from pydantic import BaseModel, Field, field_validator
from typing import List

class PickingRead(BaseModel):
    seq: int
    kit_seq: int
    order_no: str          # ← int 아님, VARCHAR(12) '700007502405'
    item_code: str
    item_seq: Optional[int] = None
    item_name: Optional[str] = None
    req_qty: int
    picked_qty: int
    uom: Optional[str] = None
    sloc: Optional[str] = None
    lpn_type: Optional[str] = None
    lpn_master_seq: Optional[int] = None
    status: str
    src_lines: Optional[int] = None

class WLpnItem(BaseModel):
    item_seq: int
    item_code: str
    init_qty: int = Field(..., gt=0)


class InsertWLpn(BaseModel):
    lpn_code: str = Field(..., max_length=30)
    lpn_type: str = Field(..., max_length=10)
    process_status: str = Field(..., max_length=20)
    location_seq: Optional[int] = None
    items: List[WLpnItem] = Field(..., min_length=1)


class DLpnItem(BaseModel):
    item_seq: int
    init_qty: int = Field(..., gt=0)

class InsertDLpn(BaseModel):
    lpn_code: str = Field(..., max_length=30)
    lpn_type: str = Field(..., max_length=10)
    process_status: str = Field(..., max_length=20)
    location_seq: Optional[int] = None
    items: List[WLpnItem] = Field(..., min_length=1)
