from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, Field


class AmrRecordLog(BaseModel):
    job_type:    Literal["ITEM", "BLOCK"]
    status:      str = Field(..., max_length=100)
    pallet_no:   Optional[int] = None
    model:       Optional[str] = Field(None, max_length=18)
    engine_no:   Optional[str] = Field(None, max_length=30)
    w_lpn_list:  Optional[List[str]] = None
    status_date: Optional[datetime] = None
    remark:      Optional[str] = Field(None, max_length=200)

class LogisticsRecordLog(BaseModel):
    """물류 AMR 이력. K-LPN 운반 상태 전이."""
    status: str = Field(..., max_length=100)
    k_lpn_code: Optional[str] = Field(None, max_length=30)
    kit_seq: Optional[int] = None
    kit_no: Optional[str] = Field(None, max_length=30)
    station_no: Optional[int] = None
    station_name: Optional[str] = Field(None, max_length=50)
    dest_code: Optional[str] = Field(None, max_length=30)
    model: Optional[str] = Field(None, max_length=18)
    engine_no: Optional[str] = Field(None, max_length=30)
    status_date: Optional[datetime] = None
    remark: Optional[str] = Field(None, max_length=200)