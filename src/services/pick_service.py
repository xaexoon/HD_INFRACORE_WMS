from src.queries import pick_query
from src.logger.logger import get_logger
from src.db.connection import query, transaction

logger = get_logger("Pick Service")

# pick_service.py

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

def get_all_picking_list():
    return query(pick_query.SELECT_ALL)

def get_pick_list_grp_kit() -> dict:
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

def get_pick_by_seq(seq:int):
    rows = query(pick_query.SELECT_BY_SEQ_GROUP_KIT, (seq,))

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


def issue_w_lpn(kit_seq: int) -> dict:
    with transaction() as cur:
        lpn_seq = insert_lpn(cur, kit_seq, "W")

    if lpn_seq is None:
        raise RuntimeError(f"세척 자재 없음: kit_seq={kit_seq}")

    return {"kit_seq": kit_seq, "lpn_seq": lpn_seq}


def issue_d_lpn(kit_seq: int) -> dict:
    with transaction() as cur:
        lpn_seq = insert_lpn(cur, kit_seq, "D")

    if lpn_seq is None:
        raise RuntimeError(f"비세척 자재 없음: kit_seq={kit_seq}")

    return {"kit_seq": kit_seq, "lpn_seq": lpn_seq}

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


def insert_w_lpn(cur, kit_seq: int) -> int | None:
    return insert_lpn(cur, kit_seq, "W")


def insert_d_lpn(cur, kit_seq: int) -> int | None:
    return insert_lpn(cur, kit_seq, "D")