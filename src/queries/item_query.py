
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

# 자재코드 또는 자재명 부분 검색 (화면 검색창용)
SEARCH = SELECT_BASE + """
WHERE (i.item_code LIKE ? OR i.item_name LIKE ?)
ORDER BY i.item_code
"""

# ── 등록/수정 ───────────────────────────────────────────────
INSERT = """
INSERT INTO item_master (rack_code, item_name, uom, washing_yn, mixed_allow, kitting_grp)
VALUES (?, ?, ?, ?, ?, ?)
"""

