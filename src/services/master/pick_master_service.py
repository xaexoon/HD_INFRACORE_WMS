from src.queries.master import pick_master_query
from src.db.connection import query, execute
from src.logger.logger import get_logger

logger = get_logger("Pick Service")


# ── 조회 ───────────────────────────────────────────────────
def get_wait_list() -> list[dict]:
    """확정 대기 목록 + 하위 자재까지 한 번에."""
    groups = query(pick_master_query.SELECT_WAIT_LIST)
    items  = query(pick_master_query.SELECT_WAIT_ITEMS_ALL)

    bucket: dict[tuple, list] = {}
    for it in items:
        bucket.setdefault((it["ORDER_NO"], it["VORNR"]), []).append(it)

    for g in groups:
        g["items"] = bucket.get((g["ORDER_NO"], g["PROC_CODE"]), [])
    return groups

def get_items(order_no: str, vornr: str) -> list[dict]:
    """[보기] — 해당 공정의 하위 자재 목록. W/D 로 나눠서 반환."""
    rows = query(pick_master_query.SELECT_ITEMS, (order_no, vornr))
    return {
        "items": rows,
        "wash_items": [r for r in rows if r["LPN_TYPE"] == "W"],
        "dry_items":  [r for r in rows if r["LPN_TYPE"] == "D"],
        "total_cnt":  len(rows),
        "short_cnt":  sum(1 for r in rows if r["is_short"]),
    }


def get_invalid(order_no: str, vornr: str) -> list[dict]:
    """확정 전 검증. 결과가 있으면 확정 차단."""
    return query(pick_master_query.SELECT_INVALID, (order_no, vornr))


# ── 확정 ───────────────────────────────────────────────────
def confirm(order_no: str, vornr: str, worker_id: str) -> dict:
    """피킹 JOB 확정.

    PDF 출고 1단계 '피킹 JOB 확정(Assign) + W/D-LPN 라벨 선발행'.
    kit_table 생성 → W/D-LPN 발행 → pick_table ISSUED 까지 한 트랜잭션.
    """
    invalid = get_invalid(order_no, vornr)
    if invalid:
        raise ValueError(f"마스터 미등록 자재 {len(invalid)}건이 있어 확정할 수 없습니다")

    items = query(pick_master_query.SELECT_ITEMS, (order_no, vornr))
    if not items:
        raise ValueError("확정할 피킹 대상이 없습니다")

    need_wash = any(r["LPN_TYPE"] == "W" for r in items)
    need_dry  = any(r["LPN_TYPE"] == "D" for r in items)

    # TODO: 아래 3개는 트랜잭션으로 묶어야 함 (현재 execute 는 건별 커밋)
    kit_seq = _create_kit(order_no, vornr)
    w_seq = _issue_lpn(kit_seq, "W") if need_wash else None
    d_seq = _issue_lpn(kit_seq, "D") if need_dry else None

    affected = execute(pick_master_query.ISSUE_PICK, (kit_seq, order_no, vornr))

    logger.info("피킹 확정: order=%s proc=%s kit=%s W=%s D=%s items=%s by=%s",
                order_no, vornr, kit_seq, w_seq, d_seq, affected, worker_id)

    return {
        "kit_seq": kit_seq,
        "w_lpn_seq": w_seq,
        "d_lpn_seq": d_seq,
        "issued_cnt": affected,
    }