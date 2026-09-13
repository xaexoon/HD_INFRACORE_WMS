from src.queries.master import rack_master_query
from src.db.connection import query, execute, transaction
from src.logger.logger import get_logger
from src.schemas.master import rack_master_schema

logger = get_logger("svc.rackm")


# ── 조회 ───────────────────────────────────────────────────
def get_all_racks() -> list[dict]:
    return query(rack_master_query.SELECT_ALL)


def get_racks_by_search(keyword: str) -> list[dict]:
    like = f"%{keyword}%"
    return query(rack_master_query.SELECT_BY_CODE, (like, like))


def get_rack_by_seq(seq: int) -> dict | None:
    """랙 1건 + 셀 목록. 쿼리는 셀 수만큼 행이 반복되므로 여기서 묶어준다."""
    rows = query(rack_master_query.SELECT_BY_SEQ, (seq,))
    if not rows:
        return None

    first = rows[0]
    rack = {
        "seq": first["seq"],
        "rack_code": first["rack_code"],
        "rack_name": first["rack_name"],
        "zone_seq": first["zone_seq"],
        "zone_code": first["zone_code"],
        "zone_name": first["zone_name"],
        "rows": first["rows"],
        "cols": first["cols"],
        "enable_yn": first["enable_yn"],
        "created_date": first["created_date"],
        "updated_date": first["updated_date"],
        "locations": [],
    }
    for r in rows:
        if r["location_seq"] is None:   # 셀이 없는 랙은 LEFT JOIN 으로 1행이 나옴
            continue
        rack["locations"].append({
            "location_seq": r["location_seq"],
            "location_code": r["location_code"],
            "row_no": r["row_no"],
            "col_no": r["col_no"],
            "enable_yn": r["location_enable_yn"],
        })
    return rack


# ── 중복 검사 ───────────────────────────────────────────────
def exists_rack_code(rack_code: str, except_seq: int | None = None) -> bool:
    if except_seq:
        rows = query(rack_master_query.EXISTS_CODE_EXCEPT_SELF, (rack_code, except_seq))
    else:
        rows = query(rack_master_query.EXISTS_CODE, (rack_code,))
    return bool(rows)


# ── 등록 / 수정 ─────────────────────────────────────────────
def insert_rack_master(body: rack_master_schema.RackInsert) -> int:
    """랙 등록 + 셀 일괄 생성."""
    execute(rack_master_query.INSERT, (
        body.rack_code,
        body.rack_name,
        body.zone_seq,
        body.rows,
        body.cols,
    ))

    rack = query(rack_master_query.EXISTS_CODE_SEQ, (body.rack_code,))
    rack_seq = rack[0]["seq"]

    cell_cnt = 0
    if body.rows and body.cols:
        cell_cnt = execute(rack_master_query.INSERT_LOCATIONS,
                           (body.rows, body.cols, rack_seq))

    logger.info("랙 등록: %s (seq=%s, 셀 %s개)", body.rack_code, rack_seq, cell_cnt)
    return rack_seq


def update_rack_master(body: rack_master_schema.RackUpdate) -> int:
    """랙 수정. 층/칸이 늘어났으면 셀을 추가로 생성한다(기존 셀은 유지)."""
    affected = execute(rack_master_query.UPDATE, (
        body.rack_code, body.rack_name, body.zone_seq,
        body.rows, body.cols, body.enable_yn, body.seq,
    ))

    if affected and body.rows and body.cols:
        added = execute(rack_master_query.INSERT_LOCATIONS,
                        (body.rows, body.cols, body.seq))
        if added:
            logger.info("셀 증설: seq=%s +%s개", body.seq, added)

    logger.info("랙 수정: seq=%s code=%s", body.seq, body.rack_code)
    return affected


# ── 사용중지 / 삭제 ─────────────────────────────────────────
def disable_rack_master(seq: int) -> int:
    affected = execute(rack_master_query.DISABLE, (seq,))
    logger.info("랙 사용중지: seq=%s", seq)
    return affected


def check_deletable(seq: int) -> dict:
    """삭제를 막는 참조가 있는지 센다.

    셀 개수로 막으면 안 된다. 랙을 등록하면 셀이 곧바로 생기므로
    그 조건은 사실상 영구 차단이 된다.
    실제로 막아야 하는 것은 그 셀을 참조하는 재고 / 지시 / 이력이다.
    """
    rows = query(rack_master_query.CHECK_DELETABLE, (seq,) * 5)
    if not rows:
        return {"location_cnt": 0, "lpn_cnt": 0, "pick_cnt": 0, "txn_cnt": 0}
    return rows[0]


def delete_rack_master(seq: int) -> int:
    """랙 삭제. 하위 셀을 먼저 지운다.

    location_master.rack_seq 에 FK(NO_ACTION)가 걸려 있어 셀이 남아 있으면
    랙만 지우는 것은 FK 위반으로 실패한다. 셀은 랙에 종속된 것이므로
    함께 지운다. 한 트랜잭션으로 묶어야 셀만 지워진 랙이 남지 않는다.

    참조 검사는 호출 전에 check_deletable() 로 끝내둔다.
    """
    with transaction() as cur:
        cur.execute(rack_master_query.DELETE_LOCATIONS, (seq,))
        cell_cnt = cur.rowcount

        cur.execute(rack_master_query.DELETE, (seq,))
        affected = cur.rowcount

    if affected:
        logger.info("랙 삭제: seq=%s (셀 %s개 함께 삭제)", seq, cell_cnt)
    return affected