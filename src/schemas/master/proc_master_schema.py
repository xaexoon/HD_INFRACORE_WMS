from typing import Optional
from pydantic import BaseModel, Field


class ProcOrderItem(BaseModel):
    seq:        int
    proc_order: int = Field(..., ge=1)


class ProcOrderUpdate(BaseModel):
    model:     str = Field(..., max_length=18)
    items:     list[ProcOrderItem] = Field(..., min_length=1)
    worker_id: Optional[str] = None