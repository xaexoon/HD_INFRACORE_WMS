from src.queries.master import rack_master_query
from src.db.connection import query, execute
from src.logger.logger import get_logger
from src.schemas.master import rack_master_schema

logger = get_logger("Rack Master Service")


# ── 조회 ───────────────────────────────────────────────────
def get_all_racks() -> list[dict]:
    return query(rack_master_query.SELECT_ALL)


def get_racks_by_search(keyword: str) -> list[dict]:
    like = f"%{keyword}%"
    return query(rack_master_query.SELECT_BY_CODE, (like, like))


def get_racks_by_zone(zone_seq: int) -> list[dict]:
    return query(rack_master_query.SELECT_BY_ZONE, (zone_seq,))


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
            "max_weight": r["max_weight"],
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
                           (DEFAULT_MAX_WEIGHT, body.rows, body.cols, rack_seq))

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
                        (DEFAULT_MAX_WEIGHT, body.rows, body.cols, body.seq))
        if added:
            logger.info("셀 증설: seq=%s +%s개", body.seq, added)

    logger.info("랙 수정: seq=%s code=%s", body.seq, body.rack_code)
    return affected


# ── 사용중지 / 삭제 ─────────────────────────────────────────
def disable_rack_master(seq: int) -> int:
    affected = execute(rack_master_query.DISABLE, (seq,))
    logger.info("랙 사용중지: seq=%s", seq)
    return affected


def count_locations(seq: int) -> int:
    rows = query(rack_master_query.CHECK_DELETABLE, (seq,))
    return rows[0]["location_cnt"] if rows else 0


def delete_rack_master(seq: int) -> int:
    affected = execute(rack_master_query.DELETE, (seq,))
    logger.info("랙 삭제: seq=%s", seq)
    return affected