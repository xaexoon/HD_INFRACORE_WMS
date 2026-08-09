from src.queries import rack_query
from src.db.connection import query, execute
from src.logger.logger import get_logger

logger = get_logger("Rack Service")


# ── 상단 필터 ──────────────────────────────────────────────
def get_zones() -> list[dict]:
    """랙 위치(구역) 셀렉트박스용."""
    return query(rack_query.SELECT_ZONES)


def get_racks_in_zone(zone_seq: int) -> list[dict]:
    """랙 번호 셀렉트박스용. 구역 선택 시 갱신."""
    return query(rack_query.SELECT_RACKS_IN_ZONE, (zone_seq,))


# ── 좌측 패널 : 구역 격자 ──────────────────────────────────
def get_zone_grid(zone_seq: int, rack_seq: int | None = None) -> list[dict]:
    """구역 내 모든 랙의 격자 + 셀별 적치 자재.

    반환 : [{rack_seq, rack_code, rows, cols,
             total_cell, used_cell, cells, matrix}, ...]
           cells[].lpns 에 [LPN - 자재] 구조가 담긴다.
           matrix 는 [층][칸] 2차원 배열. 미등록 좌표는 None.
    """
    if rack_seq:
        rows = query(rack_query.SELECT_ZONE_GRID_BY_RACK, (zone_seq, rack_seq))
    else:
        rows = query(rack_query.SELECT_ZONE_GRID, (zone_seq,))

    # 셀별 적치 자재 — location_seq 로 묶어 LPN 단위로 접는다
    detail = query(rack_query.SELECT_ZONE_CELL_ITEMS, (zone_seq,))
    by_loc: dict[int, list] = {}
    for d in detail:
        by_loc.setdefault(d["location_seq"], []).append(d)
    lpns_by_loc = {loc: _group_by_lpn(rs) for loc, rs in by_loc.items()}

    racks: list[dict] = []
    index: dict[int, dict] = {}

    for r in rows:
        rk = index.get(r["rack_seq"])
        if rk is None:
            rk = {
                "rack_seq":   r["rack_seq"],
                "rack_code":  r["rack_code"],
                "rack_name":  r["rack_name"],
                "rows":       r["rows"] or 0,
                "cols":       r["cols"] or 0,
                "total_cell": 0,
                "used_cell":  0,
                "cells":      [],
            }
            index[r["rack_seq"]] = rk
            racks.append(rk)

        if r["location_seq"] is None:      # 셀이 하나도 없는 랙
            continue

        rk["cells"].append({
            "location_seq":  r["location_seq"],
            "location_code": r["location_code"],
            "row_no":        r["row_no"],
            "col_no":        r["col_no"],
            "enable_yn":     r["location_enable_yn"],
            "lpn_cnt":       r["lpn_cnt"],
            "item_kind_cnt": r["item_kind_cnt"],
            "total_qty":     r["total_qty"],
            "lpns":          lpns_by_loc.get(r["location_seq"], []),
        })
        rk["total_cell"] += 1
        if r["lpn_cnt"] > 0:
            rk["used_cell"] += 1

    for rk in racks:
        rk["matrix"] = _to_matrix(rk["cells"], rk["rows"], rk["cols"])
    return racks


# ── 우측 패널 : 셀 상세 ────────────────────────────────────
def get_cell_detail(location_seq: int) -> dict | None:
    """셀 위치정보 + 적치된 LPN/자재. 빈 셀도 위치정보는 반환."""
    info = query(rack_query.SELECT_CELL_INFO, (location_seq,))
    if not info:
        return None

    rows = query(rack_query.SELECT_CELL_DETAIL, (location_seq,))
    lpns = _group_by_lpn(rows)

    cell = info[0]
    cell["lpns"] = lpns
    cell["lpn_cnt"] = len(lpns)
    cell["total_qty"] = sum(l["total_qty"] for l in lpns)
    return cell


# ── 검색 ───────────────────────────────────────────────────
def get_stock_by_item(item_code: str) -> list[dict]:
    """자재코드로 재고 위치 역추적."""
    return query(rack_query.SELECT_BY_ITEM, (item_code.strip(),))


def search_items(keyword: str) -> list[dict]:
    """자재코드 / 품명 부분일치 검색."""
    like = f"%{keyword}%"
    return query(rack_query.SELECT_BY_ITEM_KEYWORD, (like, like))


def get_by_lpn_code(lpn_code: str) -> dict | None:
    """LPN 바코드 스캔 조회."""
    rows = query(rack_query.SELECT_BY_LPN_CODE, (lpn_code.strip().upper(),))
    if not rows:
        return None
    grouped = _group_by_lpn(rows)
    return grouped[0] if grouped else None


# ── 내부 헬퍼 ──────────────────────────────────────────────
def _to_matrix(cells: list[dict], rows: int, cols: int) -> list[list[dict | None]]:
    """[층][칸] 2차원 배열. 상단이 배열 앞쪽에 오도록 층 역순으로 담는다."""
    pos = {(c["row_no"], c["col_no"]): c for c in cells
           if c["row_no"] is not None and c["col_no"] is not None}
    return [[pos.get((rn, cn)) for cn in range(1, cols + 1)]
            for rn in range(rows, 0, -1)]


def _group_by_lpn(rows: list[dict]) -> list[dict]:
    """평면 결과를 [LPN - 자재목록] 구조로 묶는다.

    한 LPN 에 자재가 여러 개(Multi-SKU)면 자재 수만큼 행이 반복되므로
    프론트가 쓰기 쉽게 접어준다.
    """
    ITEM_KEYS = ("lpn_detail_seq", "item_seq", "item_code", "item_name",
                 "uom", "washing_yn", "init_qty", "current_qty")

    result: list[dict] = []
    index: dict[int, dict] = {}

    for r in rows:
        seq = r["lpn_master_seq"]
        lpn = index.get(seq)
        if lpn is None:
            lpn = {k: v for k, v in r.items()
                   if k not in ITEM_KEYS and k != "location_seq"}
            lpn["items"] = []
            lpn["total_qty"] = 0
            index[seq] = lpn
            result.append(lpn)

        lpn["items"].append({k: r.get(k) for k in ITEM_KEYS})
        lpn["total_qty"] += r["current_qty"] or 0

    return result