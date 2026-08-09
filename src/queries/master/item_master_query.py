# -*- coding: utf-8 -*-
"""src/queries/master/item_master_query.py — 자재 마스터 SQL"""

# ── 공통 SELECT ─────────────────────────────────────────────
SELECT_BASE = """
SELECT i.seq, i.item_code, i.item_name, i.uom,
       i.washing_yn, i.mixed_allow, i.kitting_grp,
       i.use_yn, i.created_date, i.updated_date
FROM item_master i
"""

# ── 조회 ────────────────────────────────────────────────────
SELECT_ITEM_LIST = SELECT_BASE + """
WHERE i.use_yn = 1
ORDER BY i.item_code
"""

SELECT_ITEM_BY_SEQ = SELECT_BASE + """
WHERE i.seq = ?
"""

SELECT_ITEM_BY_CODE = SELECT_BASE + """
WHERE i.item_code = ?
"""

SELECT_ITEM_SEARCH = SELECT_BASE + """
WHERE i.use_yn = 1
  AND (i.item_code LIKE ? OR i.item_name LIKE ?)
ORDER BY i.item_code
"""

COUNT_ITEM_CODE = """
SELECT COUNT(*) AS cnt
FROM item_master
WHERE item_code = ?
"""

# ── 등록 ────────────────────────────────────────────────────
INSERT_ITEM = """
INSERT INTO item_master (item_code, item_name, uom,
                         washing_yn, mixed_allow, kitting_grp)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, ?, ?, ?)
"""

# ── 수정 ────────────────────────────────────────────────────
UPDATE_ITEM = """
UPDATE item_master
SET item_name    = ?,
    uom          = ?,
    washing_yn   = ?,
    mixed_allow  = ?,
    kitting_grp  = ?,
    updated_date = SYSDATETIME()
WHERE seq = ?
"""

# ── 삭제 ────────────────────────────────────────────────────
DELETE_ITEM = """
UPDATE item_master
SET use_yn       = 0,
    updated_date = SYSDATETIME()
WHERE seq = ?
  AND use_yn = 1
"""

DELETE_ITEM_HARD = """
DELETE FROM item_master
WHERE seq = ?
"""