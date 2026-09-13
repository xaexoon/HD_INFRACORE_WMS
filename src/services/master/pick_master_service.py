from src.queries.master import pick_master_query
from src.db.connection import query, execute, transaction
from src.logger.logger import get_logger
from src.services import common_service
from src.queries.master import process_seq_query
from datetime import date

logger = get_logger("svc.pickm")


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


def get_items(pick_no: str) -> dict:
    """[보기] — 해당 지시의 자재 목록. W/D 로 나눠서 반환."""
    rows = query(pick_master_query.SELECT_ITEMS, (pick_no,))
    return {
        "items": rows,
        "wash_items": [r for r in rows if r["LPN_TYPE"] == "W"],
        "dry_items":  [r for r in rows if r["LPN_TYPE"] == "D"],
        "total_cnt":  len(rows),
        "short_cnt":  sum(1 for r in rows if r["is_short"]),
    }


def get_invalid(pick_no: str) -> list[dict]:
    """마스터 미등록 검증. 결과가 있으면 확정 차단."""
    return query(pick_master_query.SELECT_INVALID, (pick_no,))


def check_stock(pick_no: str) -> list[dict]:
    """재고 부족 검증. 결과가 있으면 확정 차단."""
    return query(pick_master_query.CHECK_STOCK, (pick_no,))


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


def confirm(pick_no: str, worker_id: str) -> dict:
    """피킹 JOB 확정.

    PDF 출고 1단계 '피킹 JOB 확정(Assign)'.
    kit_table 생성 → R-LPN 할당(PLAN) → pick_table ISSUED 를 한 트랜잭션으로.
    W/D-LPN 발행은 별도 화면 소관이므로 여기서 하지 않는다.
    """
    invalid = get_invalid(pick_no)
    if invalid:
        raise ValueError(f"마스터 미등록 자재 {len(invalid)}건이 있어 확정할 수 없습니다")

    shortage = check_stock(pick_no)
    if shortage:
        names = ", ".join(f"{s['ITEM_NAME']}({s['short_qty']}개)" for s in shortage[:3])
        more = f" 외 {len(shortage) - 3}건" if len(shortage) > 3 else ""
        raise ValueError(f"재고 부족: {names}{more}")

    with transaction() as cur:
        # 중복 확정 방지. UX_kit_active 가 최후 방어지만 메시지를 위해 먼저 본다.
        cur.execute(pick_master_query.CHECK_KIT_EXISTS, (pick_no,))
        exists = cur.fetchone()
        if exists:
            raise ValueError(f"이미 확정된 지시입니다 ({exists[1]})")

        cur.execute(pick_master_query.SELECT_PICK_TARGET, (pick_no,))
        targets = cur.fetchall()
        if not targets:
            raise ValueError("확정할 피킹 대상이 없습니다")

        # 공급 순번은 그날 마지막 + 10. 분할 시 사이 값을 쓰기 위한 간격.
        plan_date = targets[0][3]
        cur.execute(process_seq_query.NEXT_DELIVERY_SEQ, (plan_date,))
        delivery_seq = cur.fetchone()[0]

        kit_no = common_service.make_doc_no(cur, "KIT")
        cur.execute(pick_master_query.INSERT_KIT, (kit_no, delivery_seq, pick_no))
        kit_seq, kit_no = cur.fetchone()

        for pick_seq, item_seq, req_qty, _ in targets:
            _allocate(cur, pick_seq, item_seq, req_qty)

        cur.execute(pick_master_query.ISSUE_PICK, (kit_seq, pick_no))

        common_service.log_status(cur, "kit_table", kit_seq, "WAIT",
                                  doc_no=kit_no, worker_id=worker_id,
                                  remark=f"확정 ({len(targets)}건)")
        common_service.log_status(cur, "pick_table", targets[0][0], "ISSUED",
                                  from_status="WAIT", doc_no=pick_no,
                                  worker_id=worker_id)

    logger.info("피킹 확정: pick_no=%s kit=%s seq=%s items=%s by=%s",
                pick_no, kit_no, delivery_seq, len(targets), worker_id)

    return {"kit_seq": kit_seq, "kit_no": kit_no, "pick_no": pick_no,
            "delivery_seq": delivery_seq, "issued_cnt": len(targets)}

# ── 확정 취소 ───────────────────────────────────────────────
# ── 확정 취소 ───────────────────────────────────────────────
def cancel(kit_seq: int, worker_id: str) -> dict:
    """확정 취소.

    피킹이 시작됐거나 W/D-LPN 이 발행됐으면 불가.
    긴급 보충이 붙어 있어도 불가 — 긴급분은 확정 단계를 건너뛴 지시라
    RESET_PICK 으로 WAIT 에 되돌리면 소속 키팅을 잃고 고아가 된다.
    긴급 취소를 먼저 해야 init_qty 복원까지 제대로 처리된다.
    """
    with transaction() as cur:
        cur.execute(pick_master_query.COUNT_PICK_STARTED, (kit_seq,))
        started = cur.fetchone()[0]
        if started > 0:
            raise ValueError(f"피킹이 진행된 건이 {started}건 있어 취소할 수 없습니다")

        cur.execute(pick_master_query.COUNT_KIT_LPN_USED, (kit_seq,))
        used = cur.fetchone()[0]
        if used > 0:
            raise ValueError("W/D-LPN 이 발행되어 취소할 수 없습니다")

        cur.execute(pick_master_query.COUNT_EMERGENCY_ATTACHED, (kit_seq,))
        urgent = cur.fetchone()[0]
        if urgent > 0:
            raise ValueError(f"긴급 보충 {urgent}건이 있어 취소할 수 없습니다. "
                             f"긴급 지시를 먼저 취소해 주세요")

        cur.execute(pick_master_query.CANCEL_TXN_PLAN, (kit_seq,))
        cur.execute(pick_master_query.RESET_PICK, (kit_seq,))
        reset_cnt = cur.rowcount

        if reset_cnt == 0:
            raise ValueError("취소할 대상이 없습니다")

        cur.execute(pick_master_query.INACTIVE_KIT, (kit_seq,))

        common_service.log_status(cur, "kit_table", kit_seq, "CANCEL",
                                  from_status="WAIT", worker_id=worker_id,
                                  remark=f"확정 취소 ({reset_cnt}건 복귀)")

    logger.info("확정 취소: kit=%s items=%s by=%s", kit_seq, reset_cnt, worker_id)
    return {"kit_seq": kit_seq, "reset_cnt": reset_cnt}

# ── 긴급 피킹 ───────────────────────────────────────────────
def get_emergency_pick_list() -> list[dict]:
    """긴급 피킹 대상 피킹리스트. 확정된 것만."""
    return query(pick_master_query.SELECT_KIT_LIST_FOR_EMERGENCY)


def get_emergency_pick_items(kit_seq: int) -> list[dict]:
    """해당 피킹리스트의 자재 + 가용재고."""
    return query(pick_master_query.SELECT_ITEM_FOR_EMERGENCY, (kit_seq,))


def add_emergency_pick(pick_seq: int, qty: int,
                       reason: str | None = None,
                       worker_id: str | None = None) -> dict:
    """긴급 피킹 지시 추가.

    기존 키팅에 자재를 보충한다. 새 kit_table 을 만들지 않는 이유는
    같은 W/D-LPN 에 담겨야 최종 K-LPN 하나로 나가기 때문.
    확정 단계를 건너뛰고 바로 ISSUED + R-LPN 할당까지 처리한다.
    """
    if qty <= 0:
        raise ValueError("수량은 1개 이상이어야 합니다")

    with transaction() as cur:
        cur.execute(pick_master_query.SELECT_PICK_FOR_EMERGENCY, (pick_seq,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"존재하지 않는 피킹라인입니다: {pick_seq}")

        (src_seq, kit_seq, order_no, item_code, item_seq, item_name,
         uom, sloc, lpn_type, vornr, arbpl, ifseq,
         engine_no, engine_seq, plan_date, model,
         kit_status, hold_yn, kit_life, w_lpn, d_lpn) = row

        if kit_seq is None:
            raise ValueError("확정되지 않은 공정입니다")
        if kit_life != "ACTIVE":
            raise ValueError("취소된 키팅입니다")
        if hold_yn:
            raise ValueError("보류 중인 키팅입니다")
        if kit_status == "KITTED":
            raise ValueError("키팅이 완료되어 자재를 추가할 수 없습니다")
        if item_seq is None:
            raise ValueError("자재마스터에 등록되지 않은 자재입니다")

        # 지시 생성. SRC_PICK_SEQ 로 어느 지시의 보충인지 추적한다.
        pick_no = common_service.make_doc_no(cur, "URG")
        cur.execute(pick_master_query.INSERT_EMERGENCY_PICK,
                    (pick_no, src_seq, kit_seq, order_no,
                     item_code, item_seq, item_name,
                     qty, uom, sloc, lpn_type, vornr, arbpl, ifseq,
                     engine_no, engine_seq, plan_date, model, reason))
        new_seq = cur.fetchone()[0]

        # R-LPN 할당
        _allocate(cur, new_seq, item_seq, qty)

        common_service.log_status(cur, "pick_table", new_seq, "ISSUED",
                                  doc_no=pick_no, worker_id=worker_id,
                                  remark=f"긴급 보충 {item_code} {qty}개 "
                                         f"(원본 pick_seq={src_seq}) / {reason or '-'}")

        # 이미 발행된 용기가 있으면 담길 수량을 늘린다
        to_lpn = w_lpn if lpn_type == "W" else d_lpn
        if to_lpn is not None:
            cur.execute(pick_master_query.ADD_LPN_DETAIL_QTY,
                        (qty, to_lpn, item_seq))
            if cur.rowcount == 0:
                cur.execute(pick_master_query.INSERT_LPN_DETAIL_ONE,
                            (to_lpn, item_seq, qty))

    logger.info("긴급 피킹 - %s kit=%s %s %s개 (%s) by=%s",
                pick_no, kit_seq, item_code, qty, reason or "-", worker_id)

    return {
        "pick_seq":     new_seq,
        "pick_no":      pick_no,
        "src_pick_seq": src_seq,
        "kit_seq":      kit_seq,
        "item_code":    item_code,
        "item_name":    item_name,
        "qty":          qty,
        "lpn_type":     lpn_type,
        "reason":       reason,
    }

def search_items(keyword: str) -> list[dict]:
    """자재 검색. 수동 입력 시 자동완성용."""
    like = f"%{keyword.strip()}%"
    return query(pick_master_query.SEARCH_ITEM, (like, like))


def add_manual_pick(order_no: str, vornr: str, engine_no: str,
                    items: list[dict],
                    plan_date: str | None = None,
                    engine_seq_no: str | None = None,
                    arbpl: str | None = None,
                    remark: str | None = None,
                    worker_id: str | None = None) -> dict:
    """수동 피킹리스트 등록.

    ERP 장애로 지시가 안 내려올 때의 비상 수단.
    BOM 이 ERP 에만 있으므로 자재를 사람이 직접 입력한다.
    정상 수신분과 구분하기 위해 SRC_TYPE = 'MANUAL'.

    items = [{"item_code": "...", "req_qty": 10}, ...]
    """
    order_no = (order_no or "").strip()
    vornr    = (vornr or "").strip()
    engine_no = (engine_no or "").strip()

    if not order_no:
        raise ValueError("오더번호를 입력해 주세요")
    if not vornr:
        raise ValueError("공정을 입력해 주세요")
    if not engine_no:
        raise ValueError("호기를 입력해 주세요")
    if not items:
        raise ValueError("자재를 한 건 이상 입력해 주세요")

    codes = [i["item_code"].strip() for i in items]
    if len(codes) != len(set(codes)):
        raise ValueError("중복된 자재가 있습니다")

    plan_date = plan_date or date.today().isoformat()

    with transaction() as cur:
        # 같은 [오더 + 공정] 이 이미 있으면 막는다
        cur.execute(pick_master_query.CHECK_PICK_EXISTS, (order_no, vornr))
        exists = cur.fetchone()
        if exists:
            raise ValueError(f"이미 등록된 지시입니다 ({exists[0]})")

        pick_no = common_service.make_doc_no(cur, "MAN")
        created = []

        for it in items:
            code = it["item_code"].strip()
            qty  = int(it["req_qty"])
            if qty <= 0:
                raise ValueError(f"수량은 1개 이상이어야 합니다: {code}")

            cur.execute(pick_master_query.SELECT_ITEM_BY_CODE, (code,))
            m = cur.fetchone()
            if m is None:
                raise ValueError(f"자재마스터에 없는 자재입니다: {code}")

            item_seq, item_code, item_name, uom, washing_yn = m
            lpn_type = "W" if washing_yn else "D"

            cur.execute(pick_master_query.INSERT_MANUAL_PICK,
                        (pick_no, order_no,
                         item_code, item_seq, item_name,
                         qty, uom, None, lpn_type,
                         vornr, arbpl,
                         engine_no, engine_seq_no, plan_date, remark))
            created.append({
                "pick_seq":  cur.fetchone()[0],
                "item_code": item_code,
                "item_name": item_name,
                "req_qty":   qty,
                "lpn_type":  lpn_type,
            })

            common_service.log_status(cur, "pick_table", created[0]["pick_seq"], "WAIT",
                                      doc_no=pick_no, worker_id=worker_id,
                                      remark=f"수동 등록 {engine_no}/{vornr} "
                                             f"자재 {len(created)}종 / {remark or '-'}")

    logger.info("수동 피킹리스트 등록 - %s %s/%s 자재 %s종 by=%s",
                pick_no, engine_no, vornr, len(created), worker_id)

    return {
        "pick_no":   pick_no,
        "order_no":  order_no,
        "vornr":     vornr,
        "engine_no": engine_no,
        "plan_date": plan_date,
        "item_cnt":  len(created),
        "items":     created,
    }


def cancel_emergency_pick(pick_seq: int,
                          reason: str | None = None,
                          worker_id: str | None = None) -> dict:
    """긴급 피킹 취소.

    스캔 전에만 가능하다. 실물이 나간 뒤에는 반납 절차가 필요하므로 차단.
    용기에 늘려둔 init_qty 도 함께 되돌린다.
    """
    with transaction() as cur:
        cur.execute(pick_master_query.SELECT_EMERGENCY_FOR_CANCEL, (pick_seq,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"존재하지 않는 피킹라인입니다: {pick_seq}")

        (seq, pick_no, src_type, kit_seq, item_seq, item_code,
         req_qty, picked_qty, status, lpn_type, life,
         kit_status, hold_yn, w_lpn, d_lpn) = row

        if src_type != "URGENT":
            raise ValueError("긴급 지시가 아닙니다")
        if life != "ACTIVE":
            raise ValueError("이미 취소된 지시입니다")
        if hold_yn:
            raise ValueError("보류 중인 키팅입니다")
        if picked_qty > 0:
            raise ValueError(f"이미 {picked_qty}개를 꺼내 취소할 수 없습니다")
        if status != "ISSUED":
            raise ValueError(f"취소할 수 없는 상태입니다 ({status})")

        # 예약 해제
        cur.execute(pick_master_query.CANCEL_EMERGENCY_TXN, (pick_seq,))

        # 용기 수량 되돌리기 — current_qty 미만으로는 내리지 않는다
        to_lpn = w_lpn if lpn_type == "W" else d_lpn
        if to_lpn is not None:
            cur.execute(pick_master_query.SUB_LPN_DETAIL_QTY,
                        (req_qty, req_qty, to_lpn, item_seq))

        cur.execute(pick_master_query.INACTIVE_EMERGENCY_PICK, (pick_seq,))
        if cur.rowcount == 0:
            raise ValueError("취소 대상이 아닙니다")

        common_service.log_status(cur, "pick_table", pick_seq, "CANCEL",
                                  from_status="ISSUED", doc_no=pick_no,
                                  worker_id=worker_id,
                                  remark=f"긴급 취소 {item_code} {req_qty}개 "
                                         f"/ {reason or '-'}")

    logger.info("긴급 피킹 취소 - %s kit=%s %s %s개 (%s) by=%s",
                pick_no, kit_seq, item_code, req_qty, reason or "-", worker_id)

    return {
        "pick_seq":  pick_seq,
        "pick_no":   pick_no,
        "kit_seq":   kit_seq,
        "item_code": item_code,
        "qty":       req_qty,
        "reason":    reason,
    }


def split_pick(pick_no: str, items: list[dict],
               reason: str | None = None,
               worker_id: str | None = None) -> dict:
    """피킹리스트 분할.

    확정 전에만 가능. 분할본은 호기·서열이 같고 공정만 +1 이다.
    원본에 최소 1개는 남겨야 한다 — 전량 분할을 허용하면
    REQ_QTY = 0 행이 생겨 CK_PICK_QTY 를 위반한다.

    items = [{"pick_seq": 42, "qty": 10}, ...]
    """
    code = pick_no.strip().upper()

    if not items:
        raise ValueError("분할할 자재를 선택해 주세요")

    seqs = [i["pick_seq"] for i in items]
    if len(seqs) != len(set(seqs)):
        raise ValueError("중복 선택된 자재가 있습니다")

    with transaction() as cur:
        cur.execute(pick_master_query.SELECT_PICK_FOR_SPLIT, (code,))
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"존재하지 않는 지시입니다: {code}")

        src = {r[0]: r for r in rows}          # pick_seq → row
        head = rows[0]

        if head[3] is not None:                # KIT_SEQ
            raise ValueError("이미 확정된 지시는 분할할 수 없습니다")

        # 선택 검증
        for it in items:
            r = src.get(it["pick_seq"])
            if r is None:
                raise ValueError(f"이 지시에 없는 자재입니다: {it['pick_seq']}")
            if r[19] != "WAIT":                # STATUS
                raise ValueError(f"확정 전 자재만 분할할 수 있습니다 ({r[19]})")

            qty = int(it["qty"])
            if qty <= 0:
                raise ValueError(f"수량은 1개 이상이어야 합니다: {r[11]}")
            if qty >= r[16]:                   # REQ_QTY
                raise ValueError(
                    f"원본에 최소 1개는 남겨야 합니다: "
                    f"{r[11]} (지시 {r[16]}개 / 분할 {qty}개)")

        # 새 공정번호 — base+1 부터 빈 번호
        order_no = head[4]
        base = head[5]                          # VORNR
        if not str(base).isdigit():
            raise ValueError(f"공정번호가 숫자가 아니어서 분할할 수 없습니다: {base}")

        cur.execute(pick_master_query.NEXT_SPLIT_VORNR, (int(base), order_no))
        new_vornr = str(cur.fetchone()[0])
        cur.execute(pick_master_query.INSERT_PROC_IF_MISSING,
                    (new_vornr, f"공정 {new_vornr}(분할)",
                     str(base), new_vornr))

        new_pick_no = common_service.make_doc_no(cur, "SPL")
        created = []

        for it in items:
            r = src[it["pick_seq"]]
            qty = int(it["qty"])

            # 원본 차감 — 최소 1개 보장은 쿼리에서도 한 번 더
            cur.execute(pick_master_query.SUB_SPLIT_QTY,
                        (qty, it["pick_seq"], qty))
            if cur.rowcount == 0:
                raise ValueError(f"원본 수량을 차감할 수 없습니다: {r[11]}")

            cur.execute(pick_master_query.INSERT_SPLIT_PICK,
                        (new_pick_no, r[0], order_no,
                         r[11], r[12], r[13],
                         qty, r[14], r[15], r[18],
                         new_vornr, r[6], r[7],
                         r[8], r[9], r[10], reason))
            created.append({
                "pick_seq":     cur.fetchone()[0],
                "src_pick_seq": r[0],
                "item_code":    r[11],
                "item_name":    r[13],
                "qty":          qty,
                "src_req_qty":  r[16],
                "remain_qty":   r[16] - qty,
                "lpn_type":     r[18],
            })

        common_service.log_status(cur, "pick_table", created[0]["pick_seq"], "WAIT",
                                  doc_no=new_pick_no, worker_id=worker_id,
                                  remark=f"분할 {code}(공정 {base}) → 공정 {new_vornr} "
                                         f"자재 {len(created)}종 / {reason or '-'}")

    logger.info("피킹리스트 분할 - %s(공정 %s) → %s(공정 %s) 자재 %s종 by=%s",
                code, base, new_pick_no, new_vornr, len(created), worker_id)

    return {
        "src_pick_no": code,
        "src_vornr":   base,
        "pick_no":     new_pick_no,
        "vornr":       new_vornr,
        "order_no":    order_no,
        "engine_no":   head[8],
        "item_cnt":    len(created),
        "items":       created,
        "reason":      reason,
    }

def cancel_split_pick(pick_no: str,
                      reason: str | None = None,
                      worker_id: str | None = None) -> dict:
    """분할 취소. 분할본을 없애고 원본 수량을 복원한다.

    확정 전에만 가능 — 확정 후라면 확정 취소를 먼저 해야 한다.
    kit_table·W/D-LPN·PLAN 까지 되돌리는 것은 cancel() 의 책임이다.
    """
    code = pick_no.strip().upper()

    with transaction() as cur:
        cur.execute(pick_master_query.SELECT_SPLIT_FOR_CANCEL, (code,))
        rows = cur.fetchall()
        if not rows:
            raise ValueError(f"존재하지 않는 지시입니다: {code}")

        head = rows[0]
        if head[2] != "SPLIT":
            raise ValueError("분할로 생성된 지시가 아닙니다")

        # 분할본 확정 여부
        if head[4] is not None:                        # KIT_SEQ
            raise ValueError("확정된 지시입니다. 확정 취소를 먼저 해주세요")

        restored = []
        for r in rows:
            (seq, _, _, src_pick_seq, kit_seq, _, vornr,
             item_code, item_name, req_qty, picked_qty, status, _,
             src_seq, src_pick_no, src_vornr, src_req_qty,
             src_status, src_kit_seq, src_life) = r

            if status != "WAIT":
                raise ValueError(f"확정 전 지시만 취소할 수 있습니다 ({status})")
            if picked_qty > 0:
                raise ValueError(f"이미 피킹된 자재가 있습니다: {item_code}")

            if src_seq is None:
                raise ValueError(f"원본 지시를 찾을 수 없습니다: {item_code}")
            if src_life != "ACTIVE":
                raise ValueError(f"원본이 취소되어 복원할 수 없습니다: {item_code}")
            if src_kit_seq is not None or src_status != "WAIT":
                raise ValueError(
                    f"원본({src_pick_no})이 이미 확정되어 수량을 되돌릴 수 없습니다. "
                    f"원본의 확정을 먼저 취소해 주세요")

            # 원본 복원
            cur.execute(pick_master_query.ADD_SPLIT_QTY_BACK, (req_qty, src_seq))
            if cur.rowcount == 0:
                raise ValueError(f"원본 수량을 복원할 수 없습니다: {item_code}")

            # 분할본 무효화
            cur.execute(pick_master_query.INACTIVE_SPLIT_PICK, (seq,))
            if cur.rowcount == 0:
                raise ValueError(f"취소 대상이 아닙니다: {item_code}")

            restored.append({
                "pick_seq":     seq,
                "src_pick_seq": src_seq,
                "item_code":    item_code,
                "item_name":    item_name,
                "qty":          req_qty,
                "src_req_qty":  src_req_qty + req_qty,
            })

        src_pick_no = head[14]
        vornr       = head[6]

        # 분할 공정이 더 이상 안 쓰이면 마스터에서 제거
        cur.execute(pick_master_query.DELETE_PROC_IF_UNUSED, (vornr, vornr))

        common_service.log_status(cur, "pick_table", restored[0]["pick_seq"], "CANCEL",
                                  from_status="WAIT", doc_no=code,
                                  worker_id=worker_id,
                                  remark=f"분할 취소 → {src_pick_no} 복원 "
                                         f"(자재 {len(restored)}종) / {reason or '-'}")

    logger.info("분할 취소 - %s(공정 %s) → %s 복원, 자재 %s종 by=%s",
                code, vornr, src_pick_no, len(restored), worker_id)

    return {
        "pick_no":     code,
        "vornr":       vornr,
        "src_pick_no": src_pick_no,
        "item_cnt":    len(restored),
        "items":       restored,
        "reason":      reason,
    }