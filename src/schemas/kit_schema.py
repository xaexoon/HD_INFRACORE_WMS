from pydantic import BaseModel


class IssueKit(BaseModel):
    kit_seq:   int
    worker_id: str | None = None

class InsertKLpn(BaseModel):
    kit_seq:   int
    device_id: str | None = None
    worker_id: str | None = None

class VerifyKit(BaseModel):
    kit_seq:   int
    lpn_code:  str
    device_id: str | None = None
    worker_id: str | None = None