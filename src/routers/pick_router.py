from fastapi import APIRouter
from src.services import pick_service
from src.schemas import response_schema, pick_schema
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("Pick Router")


# --------------------------------------------------------
# 피킹 공정 page — 확정(ISSUED)된 피킹리스트 대상
#   1. 조회 → 2. W/D-LPN 라벨 발행 → 3. 하향 스캔
# --------------------------------------------------------
@router.get("/get/all/pick/list")
def get_all_pick_list():
    """확정된 피킹리스트 전체."""
    result = pick_service.get_pick_list_grp_kit()
    return response_schema.response(True, "확정된 피킹 리스트 전체 조회", result)


@router.get("/get/pick/{kit_seq}")
def get_pick_by_seq(kit_seq: int):
    """피킹리스트 1장. 자재 + 피킹위치까지."""
    result = pick_service.get_pick_by_seq(kit_seq)
    return response_schema.response(True, "확정된 단일 피킹리스트 조회", result)


# ── 라벨 선발행 ─────────────────────────────────────────────
@router.post("/insert/w-lpn/{kit_seq}")
def insert_w_lpn(kit_seq: int):
    try:
        data = pick_service.issue_w_lpn(kit_seq)
        return response_schema.response(True, "W-LPN 발행 완료", data)
    except Exception as e:
        logger.error(f"W-LPN 발행 실패 - {e}")
        return response_schema.response(False, str(e), None)


@router.post("/insert/d-lpn/{kit_seq}")
def insert_d_lpn(kit_seq: int):
    try:
        data = pick_service.issue_d_lpn(kit_seq)
        return response_schema.response(True, "D-LPN 발행 완료", data)
    except Exception as e:
        logger.error(f"D-LPN 발행 실패 - {e}")
        return response_schema.response(False, str(e), None)


# ── 라벨 재발행 (훼손·분실) ─────────────────────────────────
@router.post("/reissue/w-lpn/{kit_seq}")
def reissue_w_lpn(kit_seq: int):
    try:
        data = pick_service.reissue_lpn(kit_seq, "W")
        return response_schema.response(True, "W-LPN 재발행 완료", data)
    except Exception as e:
        logger.error(f"W-LPN 재발행 실패 - {e}")
        return response_schema.response(False, str(e), None)


@router.post("/reissue/d-lpn/{kit_seq}")
def reissue_d_lpn(kit_seq: int):
    try:
        data = pick_service.reissue_lpn(kit_seq, "D")
        return response_schema.response(True, "D-LPN 재발행 완료", data)
    except Exception as e:
        logger.error(f"D-LPN 재발행 실패 - {e}")
        return response_schema.response(False, str(e), None)


# ── 하향 스캔 ───────────────────────────────────────────────
@router.post("/scan/pick")
def scan_pick(body: pick_schema.ScanPick):
    """자재 행 클릭 후 R-LPN 바코드 스캔."""
    try:
        result = pick_service.scan_pick(
            body.pick_seq, body.r_lpn_code, body.device_id, body.worker_id)
    except ValueError as e:
        logger.warning(f"[pick] 스캔 거부: pick={body.pick_seq} reason={e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "피킹 완료", result)


# ── 세척 대기존 이동 ───────────────────────────────────────────────
@router.post("/move/wash/w-lpn")
def move_to_wash(body: pick_schema.MoveLpn):
    """세척 대기존 이동 — 버튼 누르고 W-LPN 스캔."""
    try:
        result = pick_service.move_to_wash(
            body.lpn_code, body.device_id, body.worker_id)
    except ValueError as e:
        logger.warning(f"[pick] 세척존 이동 거부: {body.lpn_code} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "세척 대기존 이동 완료", result)

# ── LPN 바인딩 ───────────────────────────────────────────────
@router.post("/bind/lpn")
def bind_lpn(body: pick_schema.BindLpn):
    """버퍼 적치 바인딩 — 위치 + LPN 스캔. W/D 는 서버가 판별."""
    try:
        result = pick_service.bind_lpn(
            body.lpn_code, body.location_code, body.device_id, body.worker_id)
    except ValueError as e:
        logger.warning(f"[pick] 바인딩 거부: {body.lpn_code} - {e}")
        return response_schema.response(False, str(e), None)
    return response_schema.response(True, "바인딩 완료", result)