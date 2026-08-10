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

# ── 확정 전 재고 검증 ───────────────────────────────────────
#   부족한 자재만 반환. 빈 결과면 확정 가능.
#   파라미터 : order_no, vornr
CHECK_STOCK = """
SELECT P.SEQ, P.ITEM_CODE, P.ITEM_NAME, P.REQ_QTY,
       ISNULL(S.stock_qty, 0) AS stock_qty,
       P.REQ_QTY - ISNULL(S.stock_qty, 0) AS short_qty
FROM pick_table P
OUTER APPLY (
    SELECT SUM(V.available_qty) AS stock_qty
      FROM V_LPN_ALLOCATABLE V
     WHERE V.item_seq = P.ITEM_SEQ
       AND V.lpn_type = 'R'
       AND V.process_status = 'AVAILABLE'
) S
WHERE P.ORDER_NO = ? AND P.VORNR = ?
  AND P.STATUS = 'WAIT'
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
  AND ISNULL(S.stock_qty, 0) < P.REQ_QTY
"""


# ── 확정 대상 피킹라인 ──────────────────────────────────────
#   파라미터 : order_no, vornr
SELECT_PICK_TARGET = """
SELECT SEQ, ITEM_SEQ, REQ_QTY
  FROM pick_table
 WHERE ORDER_NO = ? AND VORNR = ?
   AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""


# ── kit_table 생성 ──────────────────────────────────────────
#   최신 전송분 ORDER_H 에서 호기/모델/서열/예정일을 가져온다.
#   파라미터 : vornr, order_no, vornr
INSERT_KIT = """
INSERT INTO kit_table
    (ORDER_NO, MES_SEQ_NO, ENGINE_NO, MODEL, PLAN_DATE,
     PROC_CODE, PROC_SORT, WORK_CENTER, WORK_CENTER_NM,
     DELIVERY_SEQ, STATUS, HOLD_YN, LIFECYCLE_STATUS, SRC_ORDER_H_SEQ)
OUTPUT INSERTED.SEQ
SELECT TOP 1
       P.ORDER_NO, H.SEQNO, H.EQUNR, H.KMATN, H.GSTRS,
       ?, ISNULL(M.proc_order, 0), P.ARBPL, M.proc_name,
       ISNULL(M.proc_order, 0), 'WAIT', 0, 'ACTIVE', H.IFSEQ
  FROM pick_table P
  LEFT JOIN ORDER_H H
    ON H.AUFNR = P.ORDER_NO
   AND H.IFDAT + H.IFTIM = (SELECT MAX(H2.IFDAT + H2.IFTIM)
                              FROM ORDER_H H2 WHERE H2.AUFNR = P.ORDER_NO)
  LEFT JOIN proc_master M
    ON M.proc_code = P.VORNR AND M.use_yn = 1
 WHERE P.ORDER_NO = ? AND P.VORNR = ?
   AND P.STATUS = 'WAIT'
   AND P.LIFECYCLE_STATUS = 'ACTIVE'
"""


# ── R-LPN 할당 ──────────────────────────────────────────────
#   split_yn=1(헐린 팔레트) 우선 → receipt_date FIFO
#   파라미터 : item_seq
SELECT_ALLOCATABLE = """
SELECT V.lpn_master_seq, V.detail_seq, V.available_qty
  FROM V_LPN_ALLOCATABLE V
 WHERE V.item_seq = ?
   AND V.lpn_type = 'R'
   AND V.process_status = 'AVAILABLE'
   AND V.available_qty > 0
 ORDER BY V.split_yn DESC, V.receipt_date, V.lpn_master_seq
"""

# 차감 직전 행 잠금. 뷰 조회만으로는 잠기지 않는다.
LOCK_LPN_DETAIL = """
SELECT current_qty FROM lpn_detail WITH (UPDLOCK, HOLDLOCK) WHERE seq = ?
"""

# 할당 예약. 실제 차감은 하향 스캔 시 DONE 전환에서.
#   파라미터 : lpn_master_seq, item_seq, qty, pick_seq
INSERT_TXN_PLAN = """
INSERT INTO lpn_txn
      (txn_type, status, lpn_master_seq, item_seq, qty, PICK_SEQ)
VALUES ('PK', 'PLAN', ?, ?, ?, ?)
"""


# ── 확정 취소 ───────────────────────────────────────────────
#   파라미터 : kit_seq
CANCEL_TXN_PLAN = """
UPDATE lpn_txn
   SET status = 'CANCEL'
 WHERE status = 'PLAN'
   AND PICK_SEQ IN (SELECT SEQ FROM pick_table WHERE KIT_SEQ = ?)
"""

RESET_PICK = """
UPDATE pick_table
   SET KIT_SEQ = NULL, STATUS = 'WAIT', UPDATED_DATE = SYSDATETIME()
 WHERE KIT_SEQ = ?
   AND STATUS = 'ISSUED'
   AND PICKED_QTY = 0
"""

INACTIVE_KIT = """
UPDATE kit_table
   SET STATUS = 'CANCEL', LIFECYCLE_STATUS = 'INACTIVE',
       UPDATED_DATE = SYSDATETIME()
 WHERE SEQ = ? AND STATUS = 'WAIT'
"""

SELECT_ALLOCATABLE = """
SELECT V.lpn_master_seq, V.detail_seq, V.available_qty
  FROM V_LPN_ALLOCATABLE V
 WHERE V.item_seq = ?
   AND V.lpn_type = 'R'
   AND V.process_status = 'AVAILABLE'
   AND V.available_qty > 0
 ORDER BY V.split_yn DESC, V.receipt_date, V.lpn_master_seq
"""