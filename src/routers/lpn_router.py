from fastapi import APIRouter
router = APIRouter()


# seq 기준 LPN 조회 (R/W/D/K)
@router.get("/search/lpn/{seq}")
def search_lpn_seq (seq: int):
    return None

# code 기준 LPN 조회 (R/W/D/K)
@router.get("/search/lpn/{code}")
def search_lpn_code (code: str):
    return None


