# ═══════════════════════════════════════════════════════════
# 랙 현황 조회 쿼리 (rack_status)
#   셀 단위로 적치된 LPN 과 자재를 조회한다.
#   마스터 관리(rack_master_query)와 분리 — 이쪽은 실시간 재고 조회.
#
#   구조 : 한 셀에 여러 LPN, 한 LPN 에 여러 자재(Multi-SKU) 가능
#          최소 단위는 [셀 - LPN - 자재] 조합
#   ※ rows 는 T-SQL 예약어이므로 [rows] 로 감쌀 것
# ═══════════════════════════════════════════════════════════


# ── 1. 구역 목록 ────────────────────────────────────────────
#   상단 '랙 위치' 셀렉트박스용
SELECT_ZONES = """
SELECT
    z.seq,
    z.zone_code,
    z.zone_name,
    z.zone_type,
    COUNT(DISTINCT r.seq) AS rack_cnt
FROM zone_master z
LEFT JOIN rack_master r
    ON r.zone_seq = z.seq
   AND r.enable_yn = 1
GROUP BY z.seq, z.zone_code, z.zone_name, z.zone_type
ORDER BY z.zone_code
"""


# ── 2. 구역 내 랙 목록 ──────────────────────────────────────
#   상단 '랙 번호' 셀렉트박스용. 파라미터 : zone_seq
SELECT_RACKS_IN_ZONE = """
SELECT
    r.seq,
    r.rack_code,
    r.rack_name,
    r.[rows],
    r.cols
FROM rack_master r
WHERE r.zone_seq = ?
  AND r.enable_yn = 1
ORDER BY r.rack_code
"""


# ── 3. 구역 전체 격자 — 화면 좌측 패널 ──────────────────────
#   셀 단위 집계만 수행. 실제 LPN/자재는 8번 쿼리로 받아
#   서비스에서 셀별로 매단다.
#   빈 셀도 나와야 하므로 location_master LEFT JOIN.
#   파라미터 : zone_seq
SELECT_ZONE_GRID = """
SELECT
    r.seq              AS rack_seq,
    r.rack_code,
    r.rack_name,
    r.[rows],
    r.cols,
    r.enable_yn        AS rack_enable_yn,

    l.seq              AS location_seq,
    l.location_code,
    l.row_no,
    l.col_no,
    l.enable_yn        AS location_enable_yn,

    ISNULL(x.lpn_cnt, 0)   AS lpn_cnt,
    ISNULL(x.item_cnt, 0)  AS item_kind_cnt,
    ISNULL(x.total_qty, 0) AS total_qty
FROM rack_master r
LEFT JOIN location_master l
    ON l.rack_seq = r.seq
OUTER APPLY (
    SELECT COUNT(DISTINCT m.seq)      AS lpn_cnt,
           COUNT(DISTINCT d.item_seq) AS item_cnt,
           SUM(d.current_qty)         AS total_qty
      FROM lpn_master m
      LEFT JOIN lpn_detail d ON d.lpn_master_seq = m.seq
     WHERE m.location_seq = l.seq
       AND m.lifecycle_status = 'ACTIVE'
) x
WHERE r.zone_seq = ?
  AND r.enable_yn = 1
ORDER BY r.rack_code, l.row_no DESC, l.col_no
"""

# 랙번호 필터 선택 시. 파라미터 : zone_seq, rack_seq
SELECT_ZONE_GRID_BY_RACK = SELECT_ZONE_GRID.replace(
    "WHERE r.zone_seq = ?",
    "WHERE r.zone_seq = ?\n  AND r.seq = ?"
)


# ── 4. 셀 위치정보 — 빈 셀도 반드시 1행 ─────────────────────
#   LPN 이 없어도 "여기가 어디인지"는 보여줘야 한다.
#   파라미터 : location_seq
SELECT_CELL_INFO = """
SELECT
    l.seq              AS location_seq,
    l.location_code,
    l.row_no,
    l.col_no,
    l.enable_yn,
    r.seq              AS rack_seq,
    r.rack_code,
    r.rack_name,
    z.seq              AS zone_seq,
    z.zone_code,
    z.zone_name,
    z.zone_type
FROM location_master l
JOIN rack_master r ON r.seq = l.rack_seq
JOIN zone_master z ON z.seq = r.zone_seq
WHERE l.seq = ?
"""


# ── 5. 셀 상세 — 격자에서 칸 클릭 시 ────────────────────────
#   그 셀의 LPN 과 자재를 전부 펼친다. 파라미터 : location_seq
SELECT_CELL_DETAIL = """
SELECT
    m.seq              AS lpn_master_seq,
    m.lpn_code,
    m.lpn_type,
    m.process_status,
    m.split_yn,
    m.receipt_date,
    m.order_no,
    m.engine_no,
    m.proc_code,

    d.seq              AS lpn_detail_seq,
    i.seq              AS item_seq,
    i.item_code,
    i.item_name,
    i.uom,
    i.washing_yn,
    d.init_qty,
    d.current_qty
FROM lpn_master m
JOIN lpn_detail d
    ON d.lpn_master_seq = m.seq
JOIN item_master i
    ON i.seq = d.item_seq
WHERE m.location_seq = ?
  AND m.lifecycle_status = 'ACTIVE'
ORDER BY m.receipt_date, m.lpn_code, i.item_code
"""


# ── 6. 자재 역추적 — "이 자재 어디 있어?" ───────────────────
#   정렬은 피킹 할당 우선순위와 동일 (분할잔량 우선 → FIFO)
#   위치가 없는 LPN(CREATED/PRINTED)도 보이도록 LEFT JOIN
#   파라미터 : item_code
SELECT_BY_ITEM = """
SELECT
    z.zone_code,
    z.zone_name,
    r.rack_code,
    r.rack_name,
    l.location_code,
    l.row_no,
    l.col_no,
    m.seq              AS lpn_master_seq,
    m.lpn_code,
    m.lpn_type,
    m.process_status,
    m.split_yn,
    m.receipt_date,
    i.item_code,
    i.item_name,
    i.uom,
    d.current_qty
FROM lpn_detail d
JOIN item_master i
    ON i.seq = d.item_seq
JOIN lpn_master m
    ON m.seq = d.lpn_master_seq
   AND m.lifecycle_status = 'ACTIVE'
LEFT JOIN location_master l
    ON l.seq = m.location_seq
LEFT JOIN rack_master r
    ON r.seq = l.rack_seq
LEFT JOIN zone_master z
    ON z.seq = r.zone_seq
WHERE i.item_code = ?
  AND d.current_qty > 0
ORDER BY m.split_yn DESC, m.receipt_date
"""


# ── 7. 자재 검색 — 코드/품명 부분일치 ───────────────────────
#   파라미터 : %검색어%, %검색어%
SELECT_BY_ITEM_KEYWORD = """
SELECT
    i.item_code,
    i.item_name,
    i.uom,
    i.washing_yn,
    COUNT(DISTINCT m.seq)         AS lpn_cnt,
    COUNT(DISTINCT l.seq)         AS location_cnt,
    ISNULL(SUM(d.current_qty), 0) AS total_qty
FROM item_master i
LEFT JOIN lpn_detail d
    ON d.item_seq = i.seq
LEFT JOIN lpn_master m
    ON m.seq = d.lpn_master_seq
   AND m.lifecycle_status = 'ACTIVE'
LEFT JOIN location_master l
    ON l.seq = m.location_seq
WHERE i.item_code LIKE ?
   OR i.item_name LIKE ?
GROUP BY i.item_code, i.item_name, i.uom, i.washing_yn
ORDER BY i.item_code
"""


# ── 8. LPN 코드로 조회 — 바코드 스캔용 ──────────────────────
#   스캔했는데 안 나오면 작업자가 당황하므로 lifecycle_status 를
#   필터하지 않고 소멸된 LPN 도 상태를 그대로 보여준다.
#   파라미터 : lpn_code
SELECT_BY_LPN_CODE = """
SELECT
    m.seq              AS lpn_master_seq,
    m.lpn_code,
    m.lpn_type,
    m.process_status,
    m.lifecycle_status,
    m.split_yn,
    m.receipt_date,
    z.zone_code,
    z.zone_name,
    r.rack_code,
    r.rack_name,
    l.location_code,
    l.row_no,
    l.col_no,

    d.seq              AS lpn_detail_seq,
    i.seq              AS item_seq,
    i.item_code,
    i.item_name,
    i.uom,
    i.washing_yn,
    d.init_qty,
    d.current_qty
FROM lpn_master m
JOIN lpn_detail d
    ON d.lpn_master_seq = m.seq
JOIN item_master i
    ON i.seq = d.item_seq
LEFT JOIN location_master l
    ON l.seq = m.location_seq
LEFT JOIN rack_master r
    ON r.seq = l.rack_seq
LEFT JOIN zone_master z
    ON z.seq = r.zone_seq
WHERE m.lpn_code = ?
ORDER BY i.item_code
"""


# ── 9. 구역 내 전체 적치 자재 — 격자에 붙일 상세 ────────────
#   격자(3번)는 집계만 하므로 실제 LPN/자재는 이 쿼리로 받아
#   서비스에서 location_seq 기준으로 셀에 매단다.
#   파라미터 : zone_seq
SELECT_ZONE_CELL_ITEMS = """
SELECT
    m.location_seq,
    m.seq        AS lpn_master_seq,
    m.lpn_code,
    m.lpn_type,
    m.process_status,
    m.split_yn,
    m.receipt_date,
    d.seq        AS lpn_detail_seq,     -- 추가
    i.seq        AS item_seq,           -- 추가
    i.item_code,
    i.item_name,
    i.uom,
    i.washing_yn,
    d.init_qty,                         -- 추가
    d.current_qty
FROM lpn_master m
JOIN lpn_detail d      ON d.lpn_master_seq = m.seq
JOIN item_master i     ON i.seq = d.item_seq
JOIN location_master l ON l.seq = m.location_seq
JOIN rack_master r     ON r.seq = l.rack_seq
WHERE r.zone_seq = ?
  AND r.enable_yn = 1
  AND m.lifecycle_status = 'ACTIVE'
ORDER BY m.location_seq, m.lpn_code, i.item_code
"""