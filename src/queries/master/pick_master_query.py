# ── 목록 — 공정 단위 ────────────────────────────────────────
#   1행 = 하나의 피킹 JOB = [호기 + 공정 + 서열]
SELECT_WAIT_LIST = """
SELECT
    P.ORDER_NO,
    P.VORNR              AS PROC_CODE,
    MAX(H.EQUNR)         AS ENGINE_NO,
    MAX(H.SEQNO)         AS MES_SEQ_NO,
    MAX(H.GSTRS)         AS PLAN_DATE,
    MAX(M.proc_name)     AS PROC_NAME,
    MAX(M.proc_order)    AS PROC_SORT,
    MAX(P.ARBPL)         AS ARBPL,
    COUNT(*)             AS item_cnt,
    SUM(P.REQ_QTY)       AS total_qty,
    SUM(CASE WHEN P.LPN_TYPE = 'W' THEN 1 ELSE 0 END) AS wash_cnt,
    SUM(CASE WHEN P.LPN_TYPE = 'D' THEN 1 ELSE 0 END) AS dry_cnt,
    SUM(CASE WHEN P.ITEM_SEQ IS NULL THEN 1 ELSE 0 END) AS invalid_cnt
FROM pick_table P
LEFT JOIN ORDER_H H
    ON H.AUFNR = P.ORDER_NO
   AND H.IFDAT + H.IFTIM = (SELECT MAX(H2.IFDAT + H2.IFTIM)
                              FROM ORDER_H H2 WHERE H2.AUFNR = P.ORDER_NO)
LEFT JOIN proc_master M
    ON M.proc_code = P.VORNR AND M.use_yn = 1
WHERE P.STATUS = 'WAIT'
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
GROUP BY P.ORDER_NO, P.VORNR
ORDER BY MAX(H.GSTRS), MAX(H.SEQNO), MAX(M.proc_order)
"""


# ── 하위 자재 [보기] ────────────────────────────────────────
#   파라미터 : order_no, vornr
SELECT_ITEMS = """
SELECT
    P.SEQ, P.ITEM_CODE, P.ITEM_NAME, P.ITEM_SEQ,
    P.REQ_QTY, P.UOM, P.SLOC, P.LPN_TYPE, P.SRC_LINES,
    ISNULL(S.stock_qty, 0) AS stock_qty,
    CASE WHEN ISNULL(S.stock_qty, 0) < P.REQ_QTY THEN 1 ELSE 0 END AS is_short
FROM pick_table P
OUTER APPLY (
    SELECT SUM(V.available_qty) AS stock_qty
      FROM V_LPN_ALLOCATABLE V
     WHERE V.item_seq = P.ITEM_SEQ
       AND V.lpn_type = 'R'
       AND V.process_status = 'AVAILABLE'
) S
WHERE P.ORDER_NO = ? AND P.VORNR = ?
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
ORDER BY P.LPN_TYPE, P.ITEM_CODE
"""


# ── 확정 전 검증 — 마스터 미등록 ────────────────────────────
SELECT_INVALID = """
SELECT P.SEQ, P.ITEM_CODE, P.ITEM_NAME,
       CASE WHEN P.ITEM_SEQ IS NULL THEN 'NO_ITEM' ELSE 'NO_PROC' END AS reason
FROM pick_table P
LEFT JOIN proc_master M
    ON M.proc_code = P.VORNR AND M.use_yn = 1
WHERE P.ORDER_NO = ? AND P.VORNR = ?
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
  AND (P.ITEM_SEQ IS NULL OR M.seq IS NULL)
"""


# ── 확정 후 상태 전이 ───────────────────────────────────────
#   kit_table 생성이 끝난 뒤 호출. 파라미터 : kit_seq, order_no, vornr
ISSUE_PICK = """
UPDATE pick_table
   SET KIT_SEQ = ?, STATUS = 'ISSUED', UPDATED_DATE = SYSDATETIME()
 WHERE ORDER_NO = ? AND VORNR = ?
   AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""


SELECT_WAIT_ITEMS_ALL = """
SELECT
    P.SEQ, P.ORDER_NO, P.VORNR,
    P.ITEM_CODE, P.ITEM_NAME, P.ITEM_SEQ,
    P.REQ_QTY, P.UOM, P.SLOC, P.LPN_TYPE, P.SRC_LINES,
    ISNULL(S.stock_qty, 0) AS stock_qty,
    CASE WHEN ISNULL(S.stock_qty, 0) < P.REQ_QTY THEN 1 ELSE 0 END AS is_short
FROM pick_table P
OUTER APPLY (
    SELECT SUM(V.available_qty) AS stock_qty
      FROM V_LPN_ALLOCATABLE V
     WHERE V.item_seq = P.ITEM_SEQ
       AND V.lpn_type = 'R'
       AND V.process_status = 'AVAILABLE'
) S
WHERE P.STATUS = 'WAIT'
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
ORDER BY P.ORDER_NO, P.VORNR, P.LPN_TYPE, P.ITEM_CODE
"""