from src.queries import pick_query
from src.logger.logger import get_logger
from src.db.connection import query, transaction

logger = get_logger("Pick Service")


# ── 채번 ───────────────────────────────────────────────────
def make_lpn_code(cur, lpn_type: str) -> str:
    """LPN 코드 채번. 반드시 트랜잭션 커서를 받는다."""
    cur.execute(pick_query.NEXT_LPN_NO, (lpn_type, lpn_type, lpn_type))
    row = cur.fetchone()

    if row is None:
        raise RuntimeError(f"LPN 채번 실패: {lpn_type}")

    lpn_code, seq_no = row[0], row[1]

    if seq_no > 99999:
        raise RuntimeError(f"일련번호 소진: {lpn_type} (99999 초과)")

    logger.info(f"LPN 채번 - {lpn_code}")
    return lpn_code


def format_lpn(lpn_code: str) -> str:
    """라벨·화면 표시용. DB 저장값은 항상 하이픈 없는 12자리."""
    return f"{lpn_code[0]}-{lpn_code[1:7]}-{lpn_code[7:]}"


# ── 조회 ───────────────────────────────────────────────────
def get_all_picking_list():
    return query(pick_query.SELECT_ALL)


def get_pick_list_grp_kit() -> dict:
    """확정된 피킹리스트 전체. 키팅 단위로 묶어서 반환."""
    rows = query(pick_query.SELECT_ALL_GROUP_KIT)

    kits = {}
    for r in rows:
        k = r["kit_seq"]
        if k not in kits:
            kits[k] = {
                "kit_seq": k,
                "order_no": r["order_no"],
                "engine_seq_no": r["engine_seq_no"],
                "engine_no": r["engine_no"],
                "proc_code": r["proc_code"],
                "work_center_nm": r["work_center_nm"],
                "delivery_seq": r["delivery_seq"],
                "kit_status": r["kit_status"],
                "hold_yn": bool(r["hold_yn"]),
                "w_lpn_seq": r["w_lpn_seq"],
                "d_lpn_seq": r["d_lpn_seq"],
                "items": [],
            }
        kits[k]["items"].append({
            "seq": r["seq"],
            "item_code": r["item_code"],
            "item_name": r["item_name"],
            "req_qty": r["req_qty"],
            "picked_qty": r["picked_qty"],
            "uom": r["uom"],
            "lpn_type": r["lpn_type"],
            "status": r["status"],
        })

    return {"pick_lists": list(kits.values()), "total": len(kits)}


def get_pick_by_seq(kit_seq: int) -> dict:
    """피킹리스트 1장. 태블릿 작업 화면용.

    items 1행 = 1스캔 단위. 한 자재가 여러 팔레트에 걸리면 행이 나뉜다.
    예) A볼트 24개 → A-01-02 에서 9개 / A-03-03 에서 15개 → 2행
    """
    rows = query(pick_query.SELECT_BY_SEQ_GROUP_KIT, (kit_seq,))

    kits = {}
    for r in rows:
        k = r["kit_seq"]
        if k not in kits:
            kits[k] = {
                "kit_seq": k,
                "order_no": r["order_no"],
                "engine_seq_no": r["engine_seq_no"],
                "engine_no": r["engine_no"],
                "proc_code": r["proc_code"],
                "work_center_nm": r["work_center_nm"],
                "delivery_seq": r["delivery_seq"],
                "kit_status": r["kit_status"],
                "hold_yn": bool(r["hold_yn"]),
                "w_lpn_seq": r["w_lpn_seq"],
                "d_lpn_seq": r["d_lpn_seq"],
                "items": [],
            }
        kits[k]["items"].append({
            "seq": r["seq"],
            "txn_seq": r["txn_seq"],
            "item_code": r["item_code"],
            "item_name": r["item_name"],
            "req_qty": r["req_qty"],
            "plan_qty": r["plan_qty"],
            "picked_qty": r["picked_qty"],
            "uom": r["uom"],
            "lpn_type": r["lpn_type"],
            "status": r["status"],
            "r_lpn_code": r["r_lpn_code"],
            "location_code": r["location_code"],
            "done": r["txn_status"] == "DONE",
        })

    return {"pick_lists": list(kits.values()), "total": len(kits)}


# ── W/D-LPN 선발행 ──────────────────────────────────────────
def insert_lpn(cur, kit_seq: int, lpn_type: str) -> int | None:
    """W/D-LPN 선발행. 해당 유형 자재가 없으면 발행하지 않고 None 반환."""

    if lpn_type not in ("W", "D"):
        raise ValueError(f"지원하지 않는 LPN 유형: {lpn_type}")

    # 미등록 자재 검사
    cur.execute(pick_query.COUNT_PICK_NO_ITEM, (kit_seq,))
    if cur.fetchone()[0] > 0:
        raise RuntimeError(f"미등록 자재 존재: kit_seq={kit_seq}")

    # 대상 자재 유무
    cur.execute(pick_query.COUNT_PICK_BY_TYPE, (kit_seq, lpn_type))
    if cur.fetchone()[0] == 0:
        logger.info(f"{lpn_type} 자재 없음 - 미발행 (kit_seq={kit_seq})")
        return None

    # 키팅 정보 + 중복 발행 검사
    cur.execute(pick_query.SELECT_KIT_HEAD, (kit_seq,))
    head = cur.fetchone()
    if head is None:
        raise RuntimeError(f"키팅 정보 없음: {kit_seq}")

    already = head[4] if lpn_type == "W" else head[5]
    if already is not None:
        raise RuntimeError(f"{lpn_type}-LPN 이미 발행됨: kit_seq={kit_seq}")

    # 발행
    lpn_code = make_lpn_code(cur, lpn_type)

    cur.execute(pick_query.INSERT_LPN_MASTER,
                (lpn_code, lpn_type, kit_seq, head[0], head[1], head[2], head[3]))
    lpn_seq = cur.fetchone()[0]

    cur.execute(pick_query.INSERT_LPN_DETAIL_FROM_PICK,
                (lpn_seq, kit_seq, lpn_type))

    cur.execute(pick_query.UPDATE_KIT_LPN[lpn_type], (lpn_seq, kit_seq))

    logger.info(f"{lpn_type}-LPN 발행 - {lpn_code} (kit_seq={kit_seq})")
    return lpn_seq


def issue_w_lpn(kit_seq: int) -> dict:
    with transaction() as cur:
        lpn_seq = insert_lpn(cur, kit_seq, "W")

    if lpn_seq is None:
        raise ValueError(f"세척 자재 없음: kit_seq={kit_seq}")

    return {"kit_seq": kit_seq, "lpn_seq": lpn_seq}


def issue_d_lpn(kit_seq: int) -> dict:
    with transaction() as cur:
        lpn_seq = insert_lpn(cur, kit_seq, "D")

    if lpn_seq is None:
        raise ValueError(f"비세척 자재 없음: kit_seq={kit_seq}")

    return {"kit_seq": kit_seq, "lpn_seq": lpn_seq}


def reissue_lpn(kit_seq: int, lpn_type: str) -> dict:
    """라벨 훼손·분실 시 원본 VOID 후 재발행."""
    with transaction() as cur:
        cur.execute(pick_query.SELECT_KIT_HEAD, (kit_seq,))
        head = cur.fetchone()
        if head is None:
            raise ValueError(f"키팅 정보 없음: {kit_seq}")

        old_seq = head[4] if lpn_type == "W" else head[5]
        if old_seq is None:
            raise ValueError(f"{lpn_type}-LPN 미발행: kit_seq={kit_seq}")

        cur.execute(pick_query.VOID_LPN, (old_seq,))
        cur.execute(pick_query.CLEAR_KIT_LPN[lpn_type], (kit_seq,))

        new_seq = insert_lpn(cur, kit_seq, lpn_type)

    logger.info(f"{lpn_type}-LPN 재발행 - {old_seq} → {new_seq}")
    return {"kit_seq": kit_seq, "old_lpn_seq": old_seq, "lpn_seq": new_seq}


# ── 하향 스캔 ───────────────────────────────────────────────
def scan_pick(pick_seq: int, r_lpn_code: str,
              device_id: str | None = None,
              worker_id: str | None = None) -> dict:
    """하향 스캔.

    자재 행 클릭 → R-LPN 바코드 스캔.
    수량은 확정 시 예약된 값(lpn_txn PLAN)을 그대로 쓴다.
    """
    code = r_lpn_code.strip().upper()

    with transaction() as cur:
        # 1) 지시 확인
        cur.execute(pick_query.SELECT_PICK_LINE, (pick_seq,))
        line = cur.fetchone()
        if line is None:
            raise ValueError("존재하지 않는 피킹 지시입니다")

        (_, _, _, item_code, item_name, req_qty, picked_qty,
         lpn_type, status, w_lpn, d_lpn, hold_yn) = line

        if status != "ISSUED":
            raise ValueError(f"처리할 수 없는 상태입니다 ({status})")
        if hold_yn:
            raise ValueError("보류 중인 키팅입니다")

        # 2) 담을 용기가 발행되어 있는가
        to_lpn_seq = w_lpn if lpn_type == "W" else d_lpn
        if to_lpn_seq is None:
            raise ValueError(f"{lpn_type}-LPN 라벨을 먼저 발행해 주세요")

        # 3) 스캔한 R-LPN 검증
        cur.execute(pick_query.SELECT_R_LPN_BY_CODE, (code,))
        src = cur.fetchone()
        if src is None:
            raise ValueError(f"등록되지 않은 LPN 입니다: {code}")

        src_seq, src_type, src_status, src_loc = src
        if src_type != "R":
            raise ValueError(f"원자재 LPN 이 아닙니다 ({src_type})")
        if src_status != "AVAILABLE":
            raise ValueError(f"사용할 수 없는 상태입니다 ({src_status})")

        # 4) 이 지시로 이 팔레트에 걸린 예약이 있는가  ← 오피킹 차단
        cur.execute(pick_query.SELECT_PLAN_TXN, (pick_seq, src_seq))
        plan = cur.fetchone()
        if plan is None:
            raise ValueError(f"지시된 팔레트가 아니거나 이미 처리되었습니다: {code}")

        txn_seq, qty, item_seq, detail_seq = plan

        # 5) 잠금 후 실재고 재확인 → 차감
        cur.execute(pick_query.LOCK_DETAIL, (detail_seq,))
        cur_qty = cur.fetchone()[0]
        if cur_qty < qty:
            raise ValueError(f"실재고 부족 (보유 {cur_qty} / 지시 {qty})")

        cur.execute(pick_query.MINUS_QTY, (qty, detail_seq))

        # 6) W/D-LPN 에 적재
        cur.execute(pick_query.PLUS_QTY, (qty, to_lpn_seq, item_seq))
        to_detail = cur.fetchone()
        if to_detail is None:
            raise ValueError("대상 LPN 에 해당 자재가 없습니다")

        # 7) 이력 확정
        cur.execute(pick_query.DONE_TXN,
                    (to_lpn_seq, to_detail[0], src_loc,
                     device_id, worker_id, txn_seq))

        # 8) 잔량 처리 + 실적 누적
        cur.execute(pick_query.UPDATE_R_LPN_AFTER, (src_seq,))
        cur.execute(pick_query.UPDATE_PICKED_QTY, (qty, qty, pick_seq))

        # 9) W/D-LPN 을 PICK_COMP 로
        cur.execute(pick_query.SET_PICK_COMP, (to_lpn_seq,))

    total = picked_qty + qty
    logger.info("하향 스캔 - pick=%s lpn=%s qty=%s (%s/%s) by=%s",
                pick_seq, code, qty, total, req_qty, worker_id)

    return {
        "pick_seq":   pick_seq,
        "item_code":  item_code,
        "item_name":  item_name,
        "qty":        qty,
        "picked_qty": total,
        "req_qty":    req_qty,
        "completed":  total >= req_qty,
        "r_lpn_code": code,
    }

# ── 바인딩 ─────────────────────────────────────────────────
def bind_lpn(lpn_code: str, location_code: str,
             device_id: str | None = None,
             worker_id: str | None = None) -> dict:
    """W/D-LPN 위치 바인딩. 스캔한 LPN 유형으로 서버가 분기한다.

    W-LPN : WASH_WAIT → WASH_COMP  (세척 완료 버퍼)
    D-LPN : PICK_COMP 유지 + 위치만 등록  (비세척 버퍼)
    """
    code = lpn_code.strip().upper()
    loc  = location_code.strip().upper()

    with transaction() as cur:
        cur.execute(pick_query.SELECT_LPN_BY_CODE, (code,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"등록되지 않은 LPN 입니다: {code}")

        seq, lpn_type, status, kit_seq, old_loc, hold_yn = row

        if lpn_type not in ("W", "D"):
            raise ValueError(f"바인딩 대상이 아닙니다 ({lpn_type}-LPN)")
        if hold_yn:
            raise ValueError("보류 중인 키팅입니다")

        # 유형별 상태 검증
        if lpn_type == "W":
            if status == "WASH_COMP":
                raise ValueError("이미 바인딩된 LPN 입니다")
            if status != "WASH_WAIT":
                raise ValueError(f"세척 대기 상태가 아닙니다 ({status})")
            from_status, to_status = "WASH_WAIT", "WASH_COMP"
        else:
            if status != "PICK_COMP":
                raise ValueError(f"피킹이 완료되지 않았습니다 ({status})")
            from_status, to_status = "PICK_COMP", "PICK_COMP"

        # 지시 자재가 전부 담겼는가
        cur.execute(pick_query.COUNT_PICK_NOT_DONE, (kit_seq, lpn_type))
        not_done = cur.fetchone()[0]
        if not_done > 0:
            raise ValueError(f"미완료 피킹 {not_done}건이 남아 있습니다")

        # 위치 확인
        cur.execute(pick_query.CHECK_LOCATION, (loc,))
        location = cur.fetchone()
        if location is None:
            raise ValueError(f"사용할 수 없는 위치입니다: {loc}")
        loc_seq, zone_code = location

        # 바인딩
        cur.execute(pick_query.BIND_LOCATION,
                    (loc_seq, to_status, seq, from_status))

        cur.execute(pick_query.INSERT_TXN_MOVE,
                    (old_loc, loc_seq, device_id, worker_id, seq))

    logger.info("바인딩 - %s → %s (%s) by=%s", code, loc, zone_code, worker_id)
    return {
        "lpn_code":       code,
        "lpn_seq":        seq,
        "lpn_type":       lpn_type,
        "location_code":  loc,
        "zone_code":      zone_code,
        "process_status": to_status,
    }

def move_to_wash(lpn_code: str,
                 device_id: str | None = None,
                 worker_id: str | None = None) -> dict:
    """세척 대기존 이동. 위치 바코드가 없어 상태만 전이한다."""
    code = lpn_code.strip().upper()

    with transaction() as cur:
        cur.execute(pick_query.SELECT_LPN_BY_CODE, (code,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"등록되지 않은 LPN 입니다: {code}")

        seq, lpn_type, status, kit_seq, old_loc, hold_yn = row

        if lpn_type != "W":
            raise ValueError(f"W-LPN 이 아닙니다 ({lpn_type}-LPN)")
        if hold_yn:
            raise ValueError("보류 중인 키팅입니다")
        if status == "WASH_WAIT":
            raise ValueError("이미 세척 대기존으로 이동된 LPN 입니다")
        if status != "PICK_COMP":
            raise ValueError(f"피킹이 완료되지 않았습니다 ({status})")

        # 지시 자재가 전부 담겼는가
        cur.execute(pick_query.COUNT_PICK_NOT_DONE, (kit_seq, "W"))
        not_done = cur.fetchone()[0]
        if not_done > 0:
            raise ValueError(f"미완료 피킹 {not_done}건이 남아 있습니다")

        cur.execute(pick_query.MOVE_TO_WASH_WAIT, (seq,))
        cur.execute(pick_query.INSERT_TXN_MOVE,
                    (old_loc, None, device_id, worker_id, seq))

    logger.info("세척존 이동 - %s by=%s", code, worker_id)
    return {"lpn_code": code, "lpn_seq": seq, "process_status": "WASH_WAIT"}