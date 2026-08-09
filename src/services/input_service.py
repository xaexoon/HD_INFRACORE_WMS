# src/services/input_service.py
from datetime import datetime

from src.db.connection import query, execute, transaction
from src.logger.logger import get_logger
from src.queries import lpn_query
from src.schemas import input_schema

logger = get_logger("input_service")


# ── 내부 함수 (트랜잭션 커서 필요) ──────────────────────────

def get_all_r_lpn():
    return query(lpn_query.SELECT_R_LPN)


def get_r_lpn_by_code(lpn_code:str):
    return query(lpn_query.SELECT_R_LPN_BY_CODE, (lpn_code,))

def make_r_lpn(cur) -> str:
    """R LPN 코드 채번. 형식: R + YYMMDD + 5자리 (예: R26072300001)"""
    prefix = f"R{datetime.now().strftime('%y%m%d')}"
    cur.execute(lpn_query.NEXT_LPN_NO, ("R", f"{prefix}%"))
    next_no = cur.fetchone()[0]
    return f"{prefix}{next_no:05d}"


def insert_lpn_master(cur, lpn_code: str, lpn_type: str,
                      process_status: str) -> int:
    cur.execute(lpn_query.INSERT_MASTER,
                (lpn_code, lpn_type, process_status))
    return cur.fetchone()[0]


def insert_lpn_detail(cur, lpn_master_seq: int, item_seq: int, qty: int) -> None:
    cur.execute(lpn_query.INSERT_DETAIL,
                (lpn_master_seq, item_seq, qty, qty))


# ── 외부 진입점 (라우터가 호출) ─────────────────────────────

def insert_r_lpn(body: input_schema.InsertRLpn) -> dict:
    """R LPN 발행. 채번 + master + detail 을 한 트랜잭션으로 처리."""

    items = query(lpn_query.SELECT_ITEM_BY_CODE, (body.item_code,))
    if not items:
        raise ValueError(f"등록되지 않은 자재코드입니다: {body.item_code}")
    item = items[0]

    with transaction() as cur:
        lpn_code = make_r_lpn(cur)
        master_seq = insert_lpn_master(cur, lpn_code, "R",
                                       "CREATED")
        insert_lpn_detail(cur, master_seq, item["seq"], body.init_qty)

    logger.info(f"R LPN 발행: {lpn_code} / {item['item_code']} {body.init_qty}")

    return {
        "lpn_master_seq": master_seq,
        "lpn_code": lpn_code,
        "item_code": item["item_code"],
        "item_name": item["item_name"],
        "qty": body.init_qty,
        "uom": item["uom"],
        "washing_yn": item["washing_yn"],
    }

def print_r_lpn(lpn_master_seq: int) -> dict:
    """R LPN 출력 처리. print_yn 0 -> 1."""

    execute(lpn_query.UPDATE_PRINT_YN_BY_SEQ, (lpn_master_seq,))

    logger.info(f"R LPN 출력 완료: {lpn_master_seq}")

    return {"lpn_master_seq": lpn_master_seq, "print_yn": 1}


def bind_r_lpn(r_lpn_seq: int, location_seq: int,
               device_id: str, worker_id: str) -> dict:
    """위치 + LPN 스캔 바인딩. 적치 완료 후 가용재고 전환."""

    with transaction() as cur:
        # 1) 위치 유효성 — 사용 가능한 셀인지, 이미 점유 중인지
        cur.execute(lpn_query.CHECK_LOCATION_USEABLE, (location_seq,))
        if not cur.fetchone():
            raise ValueError("사용할 수 없는 위치입니다")

        # 2) 상태 전이 (PRINTED -> AVAILABLE). 조건 불일치면 rowcount 0
        cur.execute(lpn_query.UPDATE_AVAILABLE, (location_seq, r_lpn_seq))
        if cur.rowcount == 0:
            raise ValueError("라벨 미출력이거나 이미 적치된 LPN입니다.")

        # 3) 재고 원장 기록 — Multi-SKU 대응으로 lpn_detail 전 행
        cur.execute(lpn_query.INSERT_TXN_IN,
                    (location_seq, device_id, worker_id, r_lpn_seq))
        if cur.rowcount == 0:
            raise ValueError("LPN 상세가 없습니다.")

    logger.info("적치 완료: lpn=%s loc=%s by=%s", r_lpn_seq, location_seq, worker_id)
    return {
        "lpn_master_seq": r_lpn_seq,
        "location_seq": location_seq,
        "process_status": "AVAILABLE",
    }

# R LPN 정보 수정
def update_r_lpn(body: input_schema.UpdateRLpn):
    if body.init_qty is None and body.current_qty is None and body.location_seq is None :
        raise ValueError("수정할 항목이 없습니다")

    with transaction() as cur:
        cur.execute(lpn_query.SELECT_BY_SEQ, (body.seq,))
        row = cur.fetchone()
        if not row :
            raise ValueError("존재하지 않는 R LPN 입니다")

        init_qty = body.init_qty if body.init_qty is not None else row.init_qty
        current_qty = body.current_qty if body.current_qty is not None else row.current_qty

        if current_qty > init_qty:
            raise ValueError("현재수량이 입고수량 보다 많을 수 없습니다")

        if body.init_qty is not None or body.current_qty is not None:
            cur.execute(lpn_query.UPDATE_DETAIL_QTY,
                        (init_qty, current_qty, row.detail_seq))

        if body.location_seq is not None:
            cur.execute(lpn_query.UPDATE_LOCATION,
                        (body.location_seq, body.seq))

    logger.info(
        f"R LPN 정정: {row.lpn_code} / "
        f"수량 {row.init_qty}→{init_qty}, 현재 {row.current_qty}→{current_qty}, "
        f"위치 {row.location_seq}→{body.location_seq} / 사유: {body.reason}"
    )

    return {
        "lpn_master_seq": body.seq,
        "lpn_code": row.lpn_code,
        "init_qty": init_qty,
        "current_qty": current_qty,
        "location_seq": body.location_seq or row.location_seq,
    }