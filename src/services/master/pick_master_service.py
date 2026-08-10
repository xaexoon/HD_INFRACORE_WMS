from src.queries.master import pick_master_query
from src.db.connection import query, execute, transaction
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


def get_items(order_no: str, vornr: str) -> dict:
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
    """마스터 미등록 검증. 결과가 있으면 확정 차단."""
    return query(pick_master_query.SELECT_INVALID, (order_no, vornr))


def check_stock(order_no: str, vornr: str) -> list[dict]:
    """재고 부족 검증. 결과가 있으면 확정 차단."""
    return query(pick_master_query.CHECK_STOCK, (order_no, vornr))


# ── 확정 ───────────────────────────────────────────────────
def _allocate(cur, pick_seq: int, item_seq: int, req_qty: int) -> None:
    """R-LPN 할당 → lpn_txn PLAN 생성.

    split_yn=1(헐린 팔레트) 우선 → receipt_date FIFO.
    한 자재가 여러 팔레트에 걸치면 PLAN 이 복수 생성된다.
    """
    cur.execute(pick_master_query.SELECT_ALLOCATABLE, (item_seq,))
    rows = cur.fetchall()

    remain = req_qty
    for lpn_master_seq, detail_seq, avail_qty in rows:
        if remain <= 0:
            break

        # 뷰 조회만으로는 잠기지 않으므로 실물 행을 잠근다
        cur.execute(pick_master_query.LOCK_LPN_DETAIL, (detail_seq,))

        take = min(remain, avail_qty)
        cur.execute(pick_master_query.INSERT_TXN_PLAN,
                    (lpn_master_seq, item_seq, take, pick_seq))
        remain -= take

    if remain > 0:
        raise ValueError(f"재고 부족 (item_seq={item_seq}, {remain}개 모자람)")


def confirm(order_no: str, vornr: str, worker_id: str) -> dict:
    """피킹 JOB 확정.

    PDF 출고 1단계 '피킹 JOB 확정(Assign)'.
    kit_table 생성 → R-LPN 할당(PLAN) → pick_table ISSUED 를 한 트랜잭션으로.
    W/D-LPN 발행은 별도 화면 소관이므로 여기서 하지 않는다.
    """
    invalid = get_invalid(order_no, vornr)
    if invalid:
        raise ValueError(f"마스터 미등록 자재 {len(invalid)}건이 있어 확정할 수 없습니다")

    shortage = check_stock(order_no, vornr)
    if shortage:
        names = ", ".join(f"{s['ITEM_NAME']}({s['short_qty']}개)" for s in shortage[:3])
        more = f" 외 {len(shortage) - 3}건" if len(shortage) > 3 else ""
        raise ValueError(f"재고 부족: {names}{more}")

    with transaction() as cur:
        cur.execute(pick_master_query.SELECT_PICK_TARGET, (order_no, vornr))
        targets = cur.fetchall()
        if not targets:
            raise ValueError("확정할 피킹 대상이 없습니다")

        cur.execute(pick_master_query.INSERT_KIT, (vornr, order_no, vornr))
        kit_seq = cur.fetchone()[0]

        for pick_seq, item_seq, req_qty in targets:
            _allocate(cur, pick_seq, item_seq, req_qty)

        cur.execute(pick_master_query.ISSUE_PICK, (kit_seq, order_no, vornr))

    logger.info("피킹 확정: order=%s proc=%s kit=%s items=%s by=%s",
                order_no, vornr, kit_seq, len(targets), worker_id)

    return {"kit_seq": kit_seq, "issued_cnt": len(targets)}


# ── 확정 취소 ───────────────────────────────────────────────
def cancel(kit_seq: int, worker_id: str) -> dict:
    """확정 취소. 피킹 시작(PICKED_QTY > 0) 전에만 가능."""
    with transaction() as cur:
        cur.execute(pick_master_query.CANCEL_TXN_PLAN, (kit_seq,))
        cur.execute(pick_master_query.RESET_PICK, (kit_seq,))
        reset_cnt = cur.rowcount

        if reset_cnt == 0:
            raise ValueError("피킹이 이미 진행된 건은 취소할 수 없습니다")

        cur.execute(pick_master_query.INACTIVE_KIT, (kit_seq,))

    logger.info("확정 취소: kit=%s items=%s by=%s", kit_seq, reset_cnt, worker_id)
    return {"kit_seq": kit_seq, "reset_cnt": reset_cnt}