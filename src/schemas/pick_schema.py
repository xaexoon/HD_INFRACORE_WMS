from typing import Optional
from pydantic import BaseModel, Field, field_validator
from typing import List

class ScanPick(BaseModel):
    pick_seq:   int
    r_lpn_code: str
    device_id:  str | None = None
    worker_id:  str | None = None

class BindLpn(BaseModel):
    lpn_code:      str
    location_code: str
    device_id:     str | None = None
    worker_id:     str | None = None

class MoveLpn(BaseModel):
    lpn_code:  str
    device_id: str | None = None
    worker_id: str | None = None