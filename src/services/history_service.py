from datetime import date

from src.queries import history_query
from src.db.connection import query
from src.logger.logger import get_logger

logger = get_logger("svc.history")


# ── 기간별 통합 ─────────────────────────────────────────
def get_txn_list(date_from: str | None = None,
                 date_to: str | None = None,
                 txn_type: str | None = None,
                 lpn_type: str | None = None,
                 zone_code: str | None = None,
                 doc_no: str | None = None,
                 location: str | None = None,
                 keyword: str = "") -> list[dict]:
    """이력 조회 메인. 날짜 미지정 시 오늘.

    필터 6종을 조건별로 조립한다. 조합이 64가지라 상수로 만들지 않는다.
    ★ params.append 순서와 SQL 조립 순서가 반드시 일치해야 한다.
    거래 단위 결과를 LPN 단위로 접어서 반환한다.
    """
    today = date.today().isoformat()
    sql = history_query.SELECT_BASE
    params: list = [date_from or today, date_to or today]

    if txn_type:
        sql += history_query.F_TXN_TYPE
        params.append(txn_type)

    if lpn_type:
        sql += history_query.F_LPN_TYPE
        params.append(lpn_type)

    if zone_code:
        sql += history_query.F_ZONE
        params.append(zone_code)

    if doc_no:
        sql += history_query.F_DOC_NO
        params += [f"%{doc_no.strip().upper()}%"] * 2

    if location:
        sql += history_query.F_LOCATION
        params += [f"%{location.strip().upper()}%"] * 2

    if keyword:
        sql += history_query.F_KEYWORD
        params += [f"%{keyword.strip()}%"] * 7

    rows = query(sql + history_query.ORDER_BY, tuple(params))
    return _group_by_lpn(rows)


# ── 셀렉트박스 소스 ────────────────────────────────────────
def get_lpn_types() -> list[dict]:
    """LPN 유형 목록."""
    return query(history_query.SELECT_LPN_TYPES)


def get_zones() -> list[dict]:
    """구역 목록."""
    return query(history_query.SELECT_ZONES)


# ── 저재고 ─────────────────────────────────────────────────
def get_low_stock(threshold: int = 10) -> list[dict]:
    """가용재고가 임계치 미만인 R-LPN. 이력 목록과 같은 구조로 반환."""
    rows = query(history_query.SELECT_LOW_STOCK, (threshold,))

    result, index = [], {}
    for r in rows:
        seq = r["lpn_master_seq"]
        lpn = index.get(seq)
        if lpn is None:
            lpn = {
                "lpn_master_seq": seq,
                "lpn_code":       r["lpn_code"],
                "lpn_type":       "R",
                "process_status": "AVAILABLE",
                "txn_type":       "LOW",
                "txn_date":       r["receipt_date"],
                "location_code":  r["location_code"],
                "zone_name":      r["zone_name"],
                "split_yn":       bool(r["split_yn"]),
                "total_qty":      0,
                "total_current_qty": 0,
                "items":          [],
            }
            index[seq] = lpn
            result.append(lpn)

        lpn["items"].append({
            "item_code":     r["item_code"],
            "item_name":     r["item_name"],
            "uom":           r["uom"],
            "washing_yn":    r["washing_yn"],
            "size_type":     r["size_type"],
            "current_qty":   r["current_qty"],
            "allocated_qty": r["allocated_qty"],
            "available_qty": r["available_qty"],
        })
        lpn["total_qty"]         += r["available_qty"] or 0
        lpn["total_current_qty"] += r["current_qty"] or 0

    return result

def _group_by_lpn(rows: list[dict]) -> list[dict]:
    """거래 목록을 LPN 단위로 접는다.

    같은 LPN 에 여러 자재가 들어간 경우 items 배열로 묶어
    화면에서 LPN 이 반복되지 않게 한다.

    수량 3종
      init_qty    라벨 인쇄값(최초 수량). 재입고해도 재발행하지 않으므로
                  라벨 표기와 실재고가 다른 것이 정상이다.
      qty         이 거래에서 움직인 수량
      current_qty 현재 남아 있는 실시간 재고
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
                "pick_no":        r["PICK_NO"],
                "kit_no":         r["KIT_NO"],
                "total_qty":      0,
                "total_init_qty":    0,
                "total_current_qty": 0,
                "total_allocated_qty": 0,
                "total_available_qty": 0,
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
            "init_qty": r["lpn_init_qty"],
            "current_qty": r["lpn_current_qty"],
            "allocated_qty": r["lpn_allocated_qty"],
            "available_qty": r["lpn_available_qty"],
            "pre_lpn_code": r["pre_lpn_code"],
            "pre_lpn_type": r["pre_lpn_type"],
        })
        lpn["total_qty"] += r["qty"] or 0
        lpn["total_init_qty"] += r["lpn_init_qty"] or 0
        lpn["total_current_qty"] += r["lpn_current_qty"] or 0
        lpn["total_allocated_qty"] += r["lpn_allocated_qty"] or 0
        lpn["total_available_qty"] += r["lpn_available_qty"] or 0

    return result

def get_history_lpn(lpn_code: str) -> dict | None:
    """LPN 상세.

    items 는 한 단계만 담는다.
      K-LPN   → W/D-LPN 목록
      W/D-LPN → R-LPN 목록
      R-LPN   → 자재 목록
    """
    code = lpn_code.strip().upper()

    head = query(history_query.SELECT_LPN_HEAD, (code,))
    if not head:
        return None
    h = head[0]
    mixed_group = []

    if h["lpn_type"] == "R":
        items = [{
            "item_code": r["item_code"],
            "item_name": r["item_name"],
            "uom": r["uom"],
            "init_qty": r["init_qty"],
            "washing_yn": bool(r["washing_yn"]),
            "mixed_allow": bool(r["mixed_allow"]),
            "kitting_grp": r["kitting_grp"],
            "current_qty": r["current_qty"],
            "allocated_qty": r["allocated_qty"],
            "available_qty": r["available_qty"],
        } for r in query(history_query.SELECT_LPN_ITEMS, (code,))]

        if any(x["mixed_allow"] and x["kitting_grp"] for x in items):
            mixed_group = query(history_query.SELECT_LPN_MIXED_GROUP, (code,))
    else:
        items = [{
            "seq":      r["seq"],
            "code":     r["lpn_code"],
            "type":     r["lpn_type"],
            "status":   r["process_status"],
            "lifecycle_status": r["lifecycle_status"],
            "location": r["location_code"],
        } for r in query(history_query.SELECT_LPN_SOURCES, (code,))]

    return {
        "seq":      h["seq"],
        "code":     h["lpn_code"],
        "type":     h["lpn_type"],
        "status":   h["process_status"],
        "lifecycle_status": h["lifecycle_status"],
        "location": h["location_code"],
        "zone_name": h["zone_name"],

        "print_yn":    bool(h["print_yn"]),
        "reprint_cnt": h["reprint_cnt"],
        "split_yn":    bool(h["split_yn"]),
        "receipt_date": h["receipt_date"],
        "created_date": h["created_date"],
        "updated_date": h["updated_date"],

        "kit_seq":    h["kit_seq"],
        "kit_no":     h["KIT_NO"],
        "kit_status": h["kit_status"],
        "work_center_nm": h["WORK_CENTER_NM"],
        "order_no":      h["order_no"],
        "engine_no":     h["engine_no"],
        "engine_seq_no": h["engine_seq_no"],
        "proc_code":     h["proc_code"],

        "items": items,
        "mixed_group" : mixed_group
    }

# ── 지시 이력 ──────────────────────────────────────────────
def get_pick_history(date_from: str | None = None,
                     date_to: str | None = None,
                     status: str | None = None,
                     pick_no: str | None = None,
                     keyword: str = "") -> list[dict]:
    """피킹리스트 이력. 1행 = [오더 + 공정] 단위 지시.

    취소·완료 건도 포함한다. 진행률은 picked_cnt / item_cnt 로 본다.
    """
    today = date.today().isoformat()
    sql = history_query.SELECT_PICK_HISTORY
    params: list = [date_from or today, date_to or today]

    if status:
        sql += history_query.F_PICK_STATUS
        params.append(status)

    if pick_no:
        sql += history_query.F_PICK_NO
        params.append(f"%{pick_no.strip().upper()}%")

    if keyword:
        sql += history_query.F_PICK_KEYWORD
        params += [f"%{keyword.strip()}%"] * 5

    return query(sql + history_query.PICK_ORDER_BY, tuple(params))


def get_pick_history_items(pick_no: str) -> dict | None:
    """피킹리스트 1건 상세. 헤더 + W/D 자재로 나눠서 반환."""
    rows = query(history_query.SELECT_PICK_HISTORY_ITEMS,
                 (pick_no.strip().upper(),))
    if not rows:
        return None

    h = rows[0]
    items = [{
        "seq":        r["SEQ"],
        "item_code":  r["ITEM_CODE"],
        "item_name":  r["ITEM_NAME"],
        "uom":        r["UOM"],
        "req_qty":    r["REQ_QTY"],
        "picked_qty": r["PICKED_QTY"],
        "lpn_type":   r["LPN_TYPE"],
        "status":     r["STATUS"],
        "lifecycle_status": r["LIFECYCLE_STATUS"],
        "created_date":     r["CREATED_DATE"],
        "updated_date":     r["UPDATED_DATE"],
    } for r in rows]

    return {
        "pick_no":       h["PICK_NO"],
        "src_type":      h["SRC_TYPE"],
        "src_pick_seq":  h["SRC_PICK_SEQ"],
        "remark":        h["REMARK"],
        "order_no":      h["ORDER_NO"],
        "proc_code":     h["VORNR"],
        "proc_name":     h["proc_name"],
        "engine_no":     h["ENGINE_NO"],
        "engine_seq_no": h["ENGINE_SEQ_NO"],
        "plan_date":     h["PLAN_DATE"],
        "kit_seq":       h["KIT_SEQ"],
        "kit_no":        h["KIT_NO"],
        "kit_status":    h["KIT_STATUS"],
        "delivery_seq":  h["DELIVERY_SEQ"],
        "w_lpn": {
            "lpn_code": h["w_lpn_code"],
            "status":   h["w_lpn_status"],
            "location": h["w_location"],
            "w_items": [x for x in items if x["lpn_type"] == "W"],
        } if h["w_lpn_code"] else None,
        "d_lpn": {
            "lpn_code": h["d_lpn_code"],
            "status":   h["d_lpn_status"],
            "location": h["d_location"],
            "d_items": [x for x in items if x["lpn_type"] == "D"],
        } if h["d_lpn_code"] else None,
        "total_cnt":  len(items),
        "picked_cnt": sum(1 for x in items if x["status"] == "PICKED"),
    }


def get_kit_history(date_from: str | None = None,
                    date_to: str | None = None,
                    status: str | None = None,
                    kit_no: str | None = None,
                    keyword: str = "") -> list[dict]:
    """키팅리스트 이력. W/D/K-LPN 과 검증 결과를 함께 본다."""
    today = date.today().isoformat()
    sql = history_query.SELECT_KIT_HISTORY
    params: list = [date_from or today, date_to or today]

    if status:
        sql += history_query.F_KIT_STATUS
        params.append(status)

    if kit_no:
        sql += history_query.F_KIT_NO
        params.append(f"%{kit_no.strip().upper()}%")

    if keyword:
        sql += history_query.F_KIT_KEYWORD
        params += [f"%{keyword.strip()}%"] * 4

    return query(sql + history_query.KIT_ORDER_BY, tuple(params))

def get_kit_history_items(kit_no: str) -> dict | None:
    """키팅리스트 1건 상세.

    헤더 + W/D/K-LPN + 자재(W/D 분리) + 3중 검증 이력.
    긴급 보충(URG)이 섞여 있으면 items 의 src_type 으로 구분한다.
    """
    code = kit_no.strip().upper()
    rows = query(history_query.SELECT_KIT_HISTORY_ITEMS, (code,))
    if not rows:
        return None

    h = rows[0]

    items = [{
        "pick_seq":   r["pick_seq"],
        "pick_no":    r["PICK_NO"],
        "src_type":   r["SRC_TYPE"],
        "item_code":  r["ITEM_CODE"],
        "item_name":  r["ITEM_NAME"],
        "uom":        r["UOM"],
        "req_qty":    r["REQ_QTY"],
        "picked_qty": r["PICKED_QTY"],
        "lpn_type":   r["LPN_TYPE"],
        "status":     r["pick_status"],
    } for r in rows if r["pick_seq"] is not None]

    verify = query(history_query.SELECT_KIT_VERIFY_BY_NO, (code,))
    return {
        "kit_seq":       h["KIT_SEQ"],
        "kit_no":        h["KIT_NO"],
        "order_no":      h["ORDER_NO"],
        "proc_code":     h["PROC_CODE"],
        "work_center_nm": h["WORK_CENTER_NM"],
        "engine_no":     h["ENGINE_NO"],
        "engine_seq_no": h["ENGINE_SEQ_NO"],
        "plan_date":     h["PLAN_DATE"],
        "delivery_seq":  h["DELIVERY_SEQ"],
        "kit_status":    h["KIT_STATUS"],
        "hold_yn":       bool(h["HOLD_YN"]),
        "lifecycle_status": h["LIFECYCLE_STATUS"],
        "created_date":  h["CREATED_DATE"],
        "updated_date":  h["UPDATED_DATE"],
        "departed_date": h["DEPARTED_DATE"],

        "w_lpn": {
            "lpn_code": h["w_lpn_code"],
            "status":   h["w_lpn_status"],
            "location": h["w_location"],
            "w_items": [x for x in items if x["lpn_type"] == "W"],
        } if h["w_lpn_code"] else None,
        "d_lpn": {
            "lpn_code": h["d_lpn_code"],
            "status":   h["d_lpn_status"],
            "location": h["d_location"],
            "d_items": [x for x in items if x["lpn_type"] == "D"],
        } if h["d_lpn_code"] else None,
        "k_lpn": {
            "lpn_code": h["k_lpn_code"],
            "status":   h["k_lpn_status"],
        } if h["k_lpn_code"] else None,

        "total_cnt":  len(items),
        "picked_cnt": sum(1 for x in items if x["status"] == "PICKED"),
        "verify_logs": verify,
        "verify_pass": sum(1 for v in verify if v["result"] == "PASS"),
        "verify_fail": sum(1 for v in verify if v["result"] == "FAIL"),
    }

