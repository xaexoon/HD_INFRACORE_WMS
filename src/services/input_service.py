# src/services/input_service.py
from datetime import datetime

from src.db.connection import query, execute, transaction
from src.logger.logger import get_logger
from src.queries import lpn_query
from src.schemas import input_schema
from src.services import common_service

logger = get_logger("svc.input")


# ── 내부 함수 (트랜잭션 커서 필요) ──────────────────────────

def get_all_r_lpn():
    return query(lpn_query.SELECT_R_LPN)

def get_r_lpn_by_code(lpn_code:str):
    return query(lpn_query.SELECT_R_LPN_BY_CODE, (lpn_code,))

def get_r_lpn_by_item_code(item_code:str):
    return query(lpn_query.SELECT_BY_ITEM_CODE, (item_code,))

def make_r_lpn(cur) -> str:
    """R-LPN 코드 채번. 형식: R + YYMMDD + 5자리 (예: R26072300001)"""
    return common_service.make_lpn_code(cur, "R")

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
    """R-LPN 발행. 채번 + master + detail 을 한 트랜잭션으로 처리.

    자재가 2종 이상이면 Multi-SKU 팔레트다.
    입고 규칙 3에 따라 mixed_allow = 1 이고 kitting_grp 가 같아야 한다.
    """
    if not body.items:
        raise ValueError("자재를 한 건 이상 입력해 주세요")

    codes = [i.item_code.strip() for i in body.items]
    if len(codes) != len(set(codes)):
        raise ValueError("중복된 자재가 있습니다")

    # 자재 검증
    targets = []
    for it in body.items:
        code = it.item_code.strip()
        rows = query(lpn_query.SELECT_ITEM_BY_CODE, (code,))
        if not rows:
            raise ValueError(f"등록되지 않은 자재코드입니다: {code}")
        targets.append((rows[0], it.init_qty))

    # Multi-SKU 검증 — 혼적 허용 + 동일 키팅그룹
    if len(targets) > 1:
        for m, _ in targets:
            if not m["mixed_allow"]:
                raise ValueError(f"혼적이 허용되지 않는 자재입니다: {m['item_code']}")
            if not m["kitting_grp"]:
                raise ValueError(f"키팅그룹이 없어 통합할 수 없습니다: {m['item_code']}")

        grps = {m["kitting_grp"] for m, _ in targets}
        if len(grps) > 1:
            raise ValueError(f"키팅그룹이 서로 달라 통합할 수 없습니다: {', '.join(sorted(grps))}")

    with transaction() as cur:
        lpn_code = make_r_lpn(cur)
        master_seq = insert_lpn_master(cur, lpn_code, "R", "CREATED")

        created = []
        for m, qty in targets:
            insert_lpn_detail(cur, master_seq, m["seq"], qty)
            created.append({
                "item_seq":   m["seq"],
                "item_code":  m["item_code"],
                "item_name":  m["item_name"],
                "uom":        m["uom"],
                "washing_yn": bool(m["washing_yn"]),
                "qty":        qty,
            })

        summary = ", ".join(f"{c['item_code']}({c['qty']})" for c in created)
        common_service.log_status(cur, "lpn_master", master_seq, "CREATED",
                                  doc_no=lpn_code, worker_id=body.worker_id,
                                  remark=summary)

    logger.info("R LPN 발행: %s / 자재 %s종 (%s)",
                lpn_code, len(created), summary)

    return {
        "lpn_master_seq": master_seq,
        "lpn_code":       lpn_code,
        "item_cnt":       len(created),
        "kitting_grp":    targets[0][0]["kitting_grp"],
        "items":          created,
    }

def print_r_lpn(lpn_master_seq: int, worker_id: str | None = None) -> dict:
    """R LPN 출력 처리. CREATED → PRINTED."""
    with transaction() as cur:
        cur.execute(lpn_query.UPDATE_PRINTED_BY_SEQ, (lpn_master_seq,))
        if cur.rowcount == 0:
            raise ValueError("이미 발행되었거나 존재하지 않는 LPN 입니다")

        common_service.log_status(cur, "lpn_master", lpn_master_seq, "PRINTED",
                                  from_status="CREATED", worker_id=worker_id)

    logger.info("R LPN 출력 완료: %s by=%s", lpn_master_seq, worker_id)
    return {"lpn_master_seq": lpn_master_seq, "print_yn": 1}

def bind_r_lpn(r_lpn_seq: int, location_seq: int,
               device_id: str | None = None,
               worker_id: str | None = None) -> dict:
    """위치 + LPN 스캔 바인딩. 적치 완료 후 가용재고 전환."""

    with transaction() as cur:
        cur.execute(lpn_query.CHECK_LOCATION_USABLE, (location_seq,))
        if not cur.fetchone():
            raise ValueError("사용할 수 없는 위치입니다")

        cur.execute(lpn_query.UPDATE_AVAILABLE, (location_seq, r_lpn_seq))
        if cur.rowcount == 0:
            raise ValueError("라벨 미출력이거나 이미 적치된 LPN 입니다")

        cur.execute(lpn_query.INSERT_TXN_IN,
                    (location_seq, device_id, worker_id, r_lpn_seq))
        if cur.rowcount == 0:
            raise ValueError("LPN 상세 데이터가 없습니다")

        common_service.log_status(cur, "lpn_master", r_lpn_seq, "AVAILABLE",
                                  from_status="PRINTED",
                                  worker_id=worker_id, device_id=device_id)

    logger.info("적치 완료: lpn=%s loc=%s by=%s", r_lpn_seq, location_seq, worker_id)
    return {
        "lpn_master_seq": r_lpn_seq,
        "location_seq": location_seq,
        "process_status": "AVAILABLE",
    }

# R LPN 정보 수정
def update_r_lpn(body: input_schema.UpdateRLpn) -> dict:
    """R-LPN 정정. Multi-SKU 면 자재별로 수량을 각각 고친다.

    할당(PLAN)이 걸린 수량 아래로는 내릴 수 없다 —
    이미 예약된 피킹 지시가 깨지기 때문.
    """
    if not body.items and body.location_seq is None:
        raise ValueError("수정할 항목이 없습니다")

    with transaction() as cur:
        cur.execute(lpn_query.SELECT_DETAIL_FOR_UPDATE, (body.seq,))
        rows = cur.fetchall()
        if not rows:
            raise ValueError("존재하지 않는 R LPN 입니다")

        cur_map = {r[0]: r for r in rows}          # detail_seq → row
        h = rows[0]
        lpn_code, lpn_type, pstat, lstat = h[7], h[8], h[9], h[10]

        if lstat != "ACTIVE":
            raise ValueError(f"소멸된 LPN 입니다: {lpn_code}")
        if lpn_type != "R":
            raise ValueError(f"원자재 LPN 이 아닙니다 ({lpn_type}-LPN)")

        changed = []
        for it in body.items:
            r = cur_map.get(it.detail_seq)
            if r is None:
                raise ValueError(f"이 LPN 에 없는 자재입니다: {it.detail_seq}")

            detail_seq, item_seq, old_init, old_cur, item_code = r[0], r[1], r[2], r[3], r[4]
            init_qty = it.init_qty    if it.init_qty    is not None else old_init
            cur_qty  = it.current_qty if it.current_qty is not None else old_cur

            if init_qty < 0 or cur_qty < 0:
                raise ValueError(f"수량은 0 이상이어야 합니다: {item_code}")

            # 예약된 수량 아래로는 못 내린다
            cur.execute(lpn_query.COUNT_ITEM_PLAN, (body.seq, item_seq))
            planned = cur.fetchone()[0]
            if cur_qty < planned:
                raise ValueError(
                    f"피킹 예약 {planned}개가 걸려 있어 "
                    f"{cur_qty}개로 내릴 수 없습니다: {item_code}")

            if init_qty == old_init and cur_qty == old_cur:
                continue

            cur.execute(lpn_query.UPDATE_DETAIL_QTY_ONE,
                        (init_qty, cur_qty, detail_seq, body.seq))
            changed.append({
                "detail_seq":  detail_seq,
                "item_code":   item_code,
                "item_name":   r[5],
                "uom":         r[6],
                "init_qty":    init_qty,
                "current_qty": cur_qty,
                "before":      {"init_qty": old_init, "current_qty": old_cur},
            })

        loc_changed = False
        if body.location_seq is not None and body.location_seq != h[11]:
            cur.execute(lpn_query.CHECK_LOCATION_USABLE, (body.location_seq,))
            if not cur.fetchone():
                raise ValueError("사용할 수 없는 위치입니다")
            cur.execute(lpn_query.UPDATE_LOCATION, (body.location_seq, body.seq))
            loc_changed = True

        if not changed and not loc_changed:
            raise ValueError("변경된 내용이 없습니다")

        detail = " / ".join(
            f"{c['item_code']} {c['before']['current_qty']}→{c['current_qty']}"
            for c in changed) or "수량 변경 없음"
        common_service.log_status(cur, "lpn_master", body.seq, pstat,
                                  from_status=pstat, doc_no=lpn_code,
                                  worker_id=body.worker_id,
                                  remark=f"정정 {detail}"
                                         + (" / 위치 변경" if loc_changed else "")
                                         + f" / 사유: {body.reason or '-'}")

    logger.info("R LPN 정정 - %s 자재 %s건 %s by=%s",
                lpn_code, len(changed),
                "+ 위치" if loc_changed else "", body.worker_id)

    return {
        "lpn_master_seq": body.seq,
        "lpn_code":       lpn_code,
        "changed_cnt":    len(changed),
        "location_changed": loc_changed,
        "items":          changed,
        "reason":         body.reason,
    }

def get_merge_preview(lpn_code: str) -> list[dict]:
    """통합 전 LPN 내용 확인. 소스·타겟 스캔 시 각각 호출."""
    return query(lpn_query.SELECT_MERGE_PREVIEW, (lpn_code.strip().upper(),))


def merge_pallet(source_code: str, target_code: str,
                 device_id: str | None = None,
                 worker_id: str | None = None) -> dict:
    """팔레트 통합. 소스 LPN 의 자재를 타겟으로 옮기고 소스를 소멸시킨다.

    보관 효율을 위한 실물 작업이므로 수량 총합은 변하지 않는다.
    R-LPN 만 대상 — W/D-LPN 은 호기·공정에 바인딩되어 있어
    다른 지시의 용기와 합치면 오조립이 된다.
    """
    src_code = source_code.strip().upper()
    tgt_code = target_code.strip().upper()

    if src_code == tgt_code:
        raise ValueError("소스와 타겟이 같습니다")

    with transaction() as cur:
        src = _get_merge_lpn(cur, src_code, "소스")
        tgt = _get_merge_lpn(cur, tgt_code, "타겟")

        src_seq, _, _, _, _, src_loc, _, _, src_loc_code = src
        tgt_seq, _, _, _, _, tgt_loc, _, _, tgt_loc_code = tgt

        # 할당된 팔레트는 옮기면 피킹 지시가 깨진다
        for seq, code in ((src_seq, src_code), (tgt_seq, tgt_code)):
            cur.execute(lpn_query.COUNT_LPN_PLAN, (seq,))
            if cur.fetchone()[0] > 0:
                raise ValueError(f"피킹이 할당된 LPN 입니다: {code}")

        cur.execute(lpn_query.SELECT_DETAIL_FOR_MERGE, (src_seq,))
        items = cur.fetchall()
        if not items:
            raise ValueError(f"소스에 담긴 자재가 없습니다: {src_code}")

        moved = []
        for detail_seq, item_seq, qty, item_code, item_name in items:
            # 타겟에 같은 자재가 있으면 합산, 없으면 신규 행
            cur.execute(lpn_query.ADD_TARGET_QTY, (qty, qty, tgt_seq, item_seq))
            row = cur.fetchone()
            if row is None:
                cur.execute(lpn_query.INSERT_TARGET_DETAIL,
                            (tgt_seq, item_seq, qty, qty))
                row = cur.fetchone()
            tgt_detail_seq = row[0]

            cur.execute(lpn_query.CLEAR_SOURCE_QTY, (detail_seq,))

            cur.execute(lpn_query.INSERT_TXN_MERGE_PALLET,
                        (src_seq, tgt_seq, tgt_detail_seq, item_seq, qty,
                         src_loc, tgt_loc, device_id, worker_id))

            moved.append({"item_code": item_code, "item_name": item_name,
                          "qty": qty})

        cur.execute(lpn_query.INACTIVE_SOURCE_LPN, (src_seq,))
        cur.execute(lpn_query.SET_TARGET_SPLIT, (tgt_seq,))

        common_service.log_status(cur, "lpn_master", src_seq, "CONSUMED",
                                  from_status="AVAILABLE", doc_no=src_code,
                                  worker_id=worker_id, device_id=device_id,
                                  remark=f"팔레트 통합 → {tgt_code} "
                                         f"(자재 {len(moved)}종)")

    logger.info("팔레트 통합 - %s → %s (자재 %s종) by=%s",
                src_code, tgt_code, len(moved), worker_id)

    return {
        "source_lpn_code": src_code,
        "source_lpn_seq":  src_seq,
        "target_lpn_code": tgt_code,
        "target_lpn_seq":  tgt_seq,
        "location_code":   tgt_loc_code,
        "item_cnt":        len(moved),
        "items":           moved,
    }


def _get_merge_lpn(cur, lpn_code: str, label: str):
    """통합 대상 LPN 조회 + 검증."""
    cur.execute(lpn_query.SELECT_LPN_FOR_MERGE_BY_CODE, (lpn_code,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"등록되지 않은 {label} LPN 입니다: {lpn_code}")

    _, _, lpn_type, pstat, lstat, _, _, kit_seq, _ = row

    if lpn_type != "R":
        raise ValueError(f"{label}가 원자재 LPN 이 아닙니다 ({lpn_type}-LPN)")
    if lstat != "ACTIVE":
        raise ValueError(f"소멸된 {label} LPN 입니다: {lpn_code}")
    if pstat != "AVAILABLE":
        raise ValueError(f"{label} 상태가 가용이 아닙니다 ({pstat})")

    return row


def merge_items(lpn_master_seq: int, item_code: str, qty: int,
                 device_id: str | None = None,
                 worker_id: str | None = None) -> dict:
    """물리적 통합 입고. 신규 입고분을 기존 R-LPN 에 합산한다.

    새 LPN 을 발행하지 않고 기존 팔레트에 실물을 올린다.
    라벨 표기(init_qty)와 실재고가 어긋나므로 재출력이 필요할 수 있다.
    """
    if qty <= 0:
        raise ValueError("수량은 1개 이상이어야 합니다")

    items = query(lpn_query.SELECT_ITEM_BY_CODE, (item_code.strip(),))
    if not items:
        raise ValueError(f"등록되지 않은 자재코드입니다: {item_code}")
    item_seq = items[0]["seq"]

    with transaction() as cur:
        cur.execute(lpn_query.SELECT_DETAIL_BY_ITEM, (lpn_master_seq, item_seq))
        row = cur.fetchone()
        if row is None:
            raise ValueError("해당 LPN 에 같은 자재가 없습니다")

        (detail_seq, init_qty, current_qty, lpn_code,
         pstat, lstat, loc_seq, i_code, i_name, uom) = row

        if lstat != "ACTIVE":
            raise ValueError(f"소멸된 LPN 입니다: {lpn_code}")
        if pstat != "AVAILABLE":
            raise ValueError(f"적치 완료된 LPN 이 아닙니다 ({pstat})")

        cur.execute(lpn_query.ADD_MERGE_QTY, (qty, qty, detail_seq))

        cur.execute(lpn_query.INSERT_TXN_MERGE_IN,
                    (lpn_master_seq, item_seq, qty, loc_seq,
                     device_id, worker_id))

        common_service.log_status(cur, "lpn_master", lpn_master_seq, "AVAILABLE",
                                  from_status="AVAILABLE", doc_no=lpn_code,
                                  worker_id=worker_id, device_id=device_id,
                                  remark=f"통합 입고 {i_code} +{qty} "
                                         f"({current_qty} → {current_qty + qty})")

    logger.info("통합 입고 - %s %s +%s (%s → %s) by=%s",
                lpn_code, i_code, qty, current_qty, current_qty + qty, worker_id)

    return {
        "lpn_master_seq": lpn_master_seq,
        "lpn_code":       lpn_code,
        "item_code":      i_code,
        "item_name":      i_name,
        "uom":            uom,
        "add_qty":        qty,
        "init_qty":       init_qty + qty,
        "current_qty":    current_qty + qty,
    }