from src.queries import kit_query
from src.db.connection import query, transaction
from src.logger.logger import get_logger

logger = get_logger("Kit Service")


# ── 조회 ───────────────────────────────────────────────────
def get_wait_list() -> dict:
    """발행 대기 목록. ready_yn 으로 발행 버튼 활성화 판단."""
    rows = query(kit_query.SELECT_KIT_WAIT_LIST)
    return {
        "kit_lists": rows,
        "total": len(rows),
        "ready_cnt": sum(1 for r in rows if r["ready_yn"]),
    }


def get_issued_list() -> dict:
    """태블릿 키팅 작업 목록. 발행된 건만."""
    rows = query(kit_query.SELECT_KIT_ISSUED_LIST)
    return {"kit_lists": rows, "total": len(rows)}


def get_kit_items(kit_seq: int) -> list[dict]:
    """키팅 1건에 담긴 자재 목록."""
    return query(kit_query.SELECT_KIT_ITEMS, (kit_seq,))


# ── 발행 ───────────────────────────────────────────────────
def _check_ready(cur, kit_seq: int) -> dict:
    """발행 가능 여부 판정.

    '둘 다 있냐' 가 아니라 '필요한 게 다 됐냐'.
    W_LPN_SEQ 가 NULL 이면 세척 자재가 없는 공정이므로 기다리지 않는다.
    """
    cur.execute(kit_query.SELECT_KIT_STATE, (kit_seq,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"존재하지 않는 키팅입니다: {kit_seq}")

    (seq, order_no, proc_code, engine_no, engine_seq, status, hold_yn,
     life, w_seq, d_seq, w_status, w_loc, w_code,
     d_status, d_loc, d_code) = row

    if life != "ACTIVE":
        raise ValueError("취소된 키팅입니다")
    if hold_yn:
        raise ValueError("보류 중인 키팅입니다")
    if status == "ISSUED":
        raise ValueError("이미 발행된 키팅입니다")
    if status != "WAIT":
        raise ValueError(f"발행할 수 없는 상태입니다 ({status})")

    if w_seq is None and d_seq is None:
        raise ValueError("W/D-LPN 이 발행되지 않았습니다")

    # 피킹 완료 여부
    cur.execute(kit_query.COUNT_PICK_NOT_PICKED, (kit_seq,))
    not_picked = cur.fetchone()[0]
    if not_picked > 0:
        raise ValueError(f"미완료 피킹 {not_picked}건이 남아 있습니다")

    # 세척 자재가 있는 공정만 세척 완료를 확인
    if w_seq is not None and w_status != "WASH_COMP":
        raise ValueError(f"세척이 완료되지 않았습니다 (W-LPN: {w_status})")

    # 비세척 자재가 있는 공정만 버퍼 적치를 확인
    if d_seq is not None and d_loc is None:
        raise ValueError("비세척 자재가 버퍼에 적치되지 않았습니다")

    return {
        "kit_seq": seq, "order_no": order_no, "proc_code": proc_code,
        "engine_no": engine_no, "engine_seq_no": engine_seq,
        "w_lpn_code": w_code, "d_lpn_code": d_code,
    }


def issue_kit(kit_seq: int, worker_id: str | None = None) -> dict:
    """키팅 지시 발행. WAIT → ISSUED."""
    with transaction() as cur:
        info = _check_ready(cur, kit_seq)

        cur.execute(kit_query.ISSUE_KIT, (kit_seq,))

    logger.info("키팅 발행 - kit=%s %s/%s by=%s",
                kit_seq, info["engine_no"], info["proc_code"], worker_id)

    return {**info, "status": "ISSUED"}


def cancel_issue(kit_seq: int, worker_id: str | None = None) -> dict:
    """발행 취소. 키팅 착수 전에만 가능."""
    with transaction() as cur:
        cur.execute(kit_query.CANCEL_ISSUE_KIT, (kit_seq,))
        if cur.rowcount == 0:
            raise ValueError("발행 상태가 아니거나 이미 키팅이 진행되었습니다")

    logger.info("키팅 발행 취소 - kit=%s by=%s", kit_seq, worker_id)
    return {"kit_seq": kit_seq, "status": "WAIT"}