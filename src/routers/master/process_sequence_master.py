from fastapi import APIRouter
router = APIRouter()

# 공정 순서 조회
@router.get("/get/process")
def get_process():
    return None

# 공정 순서 올림
@router.get("/process/upper")
def process_upper():
    return None

# 공정 순서 내림
@router.get("/process/lower")
def process_lower():
    return None

# 공정 순서 보류
@router.get("/process/hold")
def process_hold():
    return None
