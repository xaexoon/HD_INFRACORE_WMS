from pydantic import BaseModel, Field


class EmergencyPick(BaseModel):
    pick_seq:  int
    qty:       int
    reason:    str | None = None
    worker_id: str | None = None

class CancelEmergencyPick(BaseModel):
    pick_seq:  int
    reason:    str | None = None
    worker_id: str | None = None

class ManualPickItem(BaseModel):
    item_code: str
    req_qty:   int

class ManualPick(BaseModel):
    order_no:      str
    vornr:         str
    engine_no:     str
    items:         list[ManualPickItem]
    plan_date:     str | None = None
    engine_seq_no: str | None = None
    arbpl:         str | None = None
    remark:        str | None = None
    worker_id:     str | None = None

class SplitPickItem(BaseModel):
    pick_seq: int
    qty:      int


class SplitPick(BaseModel):
    pick_no:   str
    items:     list[SplitPickItem]
    reason:    str | None = None
    worker_id: str | None = None

class CancelSplitPick(BaseModel):
    pick_no:   str
    reason:    str | None = None
    worker_id: str | None = None