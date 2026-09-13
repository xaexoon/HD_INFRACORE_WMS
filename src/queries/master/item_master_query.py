# -*- coding: utf-8 -*-
"""src/queries/master/item_master_query.py — 자재 마스터 SQL"""

# ── 공통 SELECT ─────────────────────────────────────────────
#   size_type 은 소물(S)/중물(M)/대물(L). 현업이 수기로 입력하며
#   미분류는 NULL 로 둔다.
SELECT_BASE = """
SELECT i.seq, i.item_code, i.item_name, i.uom,
       i.washing_yn, i.mixed_allow, i.kitting_grp,
       i.size_type, c.code_name AS size_name,
       i.use_yn, i.created_date, i.updated_date
FROM item_master i
LEFT JOIN common_code c ON c.group_code = 'SIZE_TYPE'
                       AND c.code = i.size_type
                       AND c.use_yn = 1
"""

# ── 조회 ────────────────────────────────────────────────────
SELECT_ITEM_LIST = SELECT_BASE + """
ORDER BY i.item_code
"""

SELECT_ITEM_BY_SEQ = SELECT_BASE + """
WHERE i.seq = ?
"""

SELECT_ITEM_BY_CODE = SELECT_BASE + """
WHERE i.item_code = ?
"""

SELECT_ITEM_SEARCH = SELECT_BASE + """
WHERE  (i.item_code LIKE ? OR i.item_name LIKE ?)
ORDER BY i.item_code
"""

# 크기 구분별 조회 — 미분류(NULL) 는 size_type 에 'NONE' 을 넘긴다
#   파라미터 : size_type
SELECT_ITEM_BY_SIZE = SELECT_BASE + """
WHERE i.use_yn = 1
  AND (? = 'NONE' AND i.size_type IS NULL OR i.size_type = ?)
ORDER BY i.item_code
"""

# 크기 구분 미입력 자재 — 수기 입력 대상 확인용
SELECT_ITEM_NO_SIZE = SELECT_BASE + """
WHERE i.use_yn = 1 AND i.size_type IS NULL
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
                         washing_yn, mixed_allow, kitting_grp, size_type)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

# ── 수정 ────────────────────────────────────────────────────
UPDATE_ITEM = """
UPDATE item_master
SET item_name    = ?,
    uom          = ?,
    washing_yn   = ?,
    mixed_allow  = ?,
    kitting_grp  = ?,
    size_type    = ?,
    updated_date = SYSDATETIME(),
    use_yn = ?
WHERE seq = ?
"""

# 크기 구분만 변경 — 목록에서 바로 수정할 때
#   파라미터 : size_type, seq
UPDATE_ITEM_SIZE = """
UPDATE item_master
SET size_type    = ?,
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


# ── 크기 구분 셀렉트박스 ────────────────────────────────────
SELECT_SIZE_TYPES = """
SELECT code, code_name, sort_order
  FROM common_code
 WHERE group_code = 'SIZE_TYPE' AND use_yn = 1
 ORDER BY sort_order
"""

# 자재가 실제로 쓰이고 있는지 — 재고 · 지시 어느 쪽이든
COUNT_ITEM_USED = """
SELECT
    (SELECT COUNT(*) FROM lpn_detail
      WHERE item_seq = ? AND current_qty > 0)                      AS stock_cnt,
    (SELECT COUNT(*) FROM pick_table
      WHERE ITEM_SEQ = ? AND LIFECYCLE_STATUS = 'ACTIVE'
        AND STATUS NOT IN ('PICKED','CANCEL'))                     AS pick_cnt
"""

# 삭제 — use_yn = 0 인 것만
DELETE_ITEM_HARD = """
DELETE FROM item_master
WHERE seq = ? AND use_yn = 0
"""