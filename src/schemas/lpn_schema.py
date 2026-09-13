from pydantic import BaseModel


class MergePallet(BaseModel):
    source_code: str
    target_code: str
    device_id:   str | None = None
    worker_id:   str | None = None
