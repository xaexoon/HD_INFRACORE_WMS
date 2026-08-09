
# ── 공통 SELECT ─────────────────────────────────────────────
SELECT_BASE = """
SELECT i.seq,
       i.item_code,
       i.item_name,
       i.uom,
       i.washing_yn,
       i.mixed_allow,
       i.kitting_grp
FROM item_master i
"""

# ── 조회 ────────────────────────────────────────────────────
SELECT_ALL = SELECT_BASE + """
ORDER BY i.item_code
"""

SELECT_BY_CODE = SELECT_BASE + """
WHERE i.item_code = ?
"""

SELECT_BY_KITTING_GRP = SELECT_BASE + """
WHERE i.kitting_grp = ?
ORDER BY i.item_code
"""

# 자재코드 또는 자재명 부분 검색 (화면 검색창용)
SEARCH = SELECT_BASE + """
WHERE (i.item_code LIKE ? OR i.item_name LIKE ?)
ORDER BY i.item_code
"""

# 자재별 현재고 요약 (활성 LPN의 current_qty 합산)
SELECT_WITH_STOCK = """
SELECT i.item_code,
       i.item_name,
       i.uom,
       i.washing_yn,
       ISNULL(SUM(d.current_qty), 0) AS total_qty,
       COUNT(d.seq) AS lpn_count
FROM item_master i
LEFT JOIN lpn_detail d ON d.item_seq = i.seq
LEFT JOIN lpn_master m ON m.seq = d.lpn_master_seq
                       AND m.lifecycle_status = 'ACTIVE'
GROUP BY i.item_code, i.item_name, i.uom, i.washing_yn
ORDER BY i.item_code
"""

# ── 등록/수정 ───────────────────────────────────────────────
INSERT = """
INSERT INTO item_master (rack_code, item_name, uom, washing_yn, mixed_allow, kitting_grp)
VALUES (?, ?, ?, ?, ?, ?)
"""

UPDATE_BY_CODE = """
UPDATE item_master
SET item_name = ?, washing_yn = ?, mixed_allow = ?, kitting_grp = ?
WHERE item_code = ?
"""