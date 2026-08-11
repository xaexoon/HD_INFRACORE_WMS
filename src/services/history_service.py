from datetime import date

from src.queries import history_query
from src.db.connection import query
from src.logger.logger import get_logger

logger = get_logger("History Service")


# ── A. 기간별 통합 ─────────────────────────────────────────
def get_txn_list(date_from: str | None = None,
                 date_to: str | None = None,
                 txn_type: str | None = None,
                 keyword: str = "",
                 lpn_type: str | None = None) -> list[dict]:
    """이력 조회 메인. 날짜 미지정 시 오늘.

    거래 단위 결과를 LPN 단위로 접어서 반환한다.
    """
    today = date.today().isoformat()
    date_from = date_from or today
    date_to   = date_to   or today

    if txn_type and keyword:
        like = f"%{keyword}%"
        params = (date_from, date_to, txn_type) + (like,) * 7
        rows = query(history_query.SELECT_BY_TYPE_KEYWORD, params)

    elif keyword:
        like = f"%{keyword}%"
        params = (date_from, date_to) + (like,) * 7
        rows = query(history_query.SELECT_BY_KEYWORD, params)

    elif txn_type:
        rows = query(history_query.SELECT_BY_TYPE, (date_from, date_to, txn_type))

    elif lpn_type:
        rows = query(history_query.SELECT_BY_LPN_TYPE, (date_from, date_to, lpn_type))

    else:
        rows = query(history_query.SELECT_BY_PERIOD, (date_from, date_to))

    return _group_by_lpn(rows)

# ── B. LPN 추적 ────────────────────────────────────────────
def get_lpn_history(lpn_code: str) -> list[dict]:
    """한 LPN 의 전체 생애. 기간 제한 없음."""
    code = lpn_code.strip().upper()
    return query(history_query.SELECT_BY_LPN, (code, code, code))


# ── C. 자재 추적 ───────────────────────────────────────────
def get_item_history(item_code: str,
                     date_from: str | None = None,
                     date_to: str | None = None) -> list[dict]:
    """자재가 어느 엔진/공정에 투입됐는지 추적."""
    today = date.today().isoformat()
    return query(history_query.SELECT_BY_ITEM,
                 (item_code.strip(), date_from or today, date_to or today))


# ── 유형 목록 ──────────────────────────────────────────────
def get_txn_types() -> list[dict]:
    """유형 셀렉트박스용."""
    return query(history_query.SELECT_TXN_TYPES)


def get_txn_by_seq(seq: int) -> dict | None:
    """이력 단건 상세. 목록에서 행 클릭 시."""
    rows = query(history_query.SELECT_BY_SEQ, (seq,))
    return rows[0] if rows else None


def get_txn_by_pick(pick_seq: int) -> list[dict]:
    """같은 피킹 지시로 묶인 거래들. 분할 할당 추적용."""
    return query(history_query.SELECT_BY_PICK_SEQ, (pick_seq,))

def _group_by_lpn(rows: list[dict]) -> list[dict]:
    """거래 목록을 LPN 단위로 접는다.

    같은 LPN 에 여러 자재가 들어간 경우 items 배열로 묶어
    화면에서 LPN 이 반복되지 않게 한다.
    """
    result: list[dict] = []
    index: dict[int, dict] = {}

    for r in rows:
        seq = r["lpn_master_seq"]
        lpn = index.get(seq)
        if lpn is None:
            lpn = {
                "lpn_master_seq": seq,
                "lpn_code":       r["lpn_code"],
                "lpn_type":       r["lpn_type"],
                "process_status": r["process_status"],
                "txn_type":       r["txn_type"],
                "txn_date":       r["txn_date"],
                "worker_id":      r["worker_id"],
                "device_id":      r["device_id"],
                "location_code":  r["to_location_code"] or r["from_location_code"],
                "zone_name":      r["zone_name"],
                "order_no":       r["order_no"],
                "engine_no":      r["engine_no"],
                "proc_code":      r["proc_code"],
                "engine_seq_no":  r["engine_seq_no"],
                "total_qty":      0,
                "items":          [],
            }
            index[seq] = lpn
            result.append(lpn)

        if r["item_code"] is None:
            continue

        lpn["items"].append({
            "txn_seq":      r["txn_seq"],
            "item_code":    r["item_code"],
            "item_name":    r["item_name"],
            "uom":          r["uom"],
            "washing_yn":   r["washing_yn"],
            "qty":          r["qty"],
            "pre_lpn_code": r["pre_lpn_code"],
            "pre_lpn_type": r["pre_lpn_type"],
        })
        lpn["total_qty"] += r["qty"] or 0

    return result