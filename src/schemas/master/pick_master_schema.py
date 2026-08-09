from pydantic import BaseModel, Field


class PickConfirm(BaseModel):
    """피킹 JOB 확정 요청"""
    order_no: str = Field(..., max_length=12, description="생산오더번호")
    vornr: str = Field(..., max_length=4, description="공정코드")
    worker_id: str = Field(..., max_length=30, description="확정자")