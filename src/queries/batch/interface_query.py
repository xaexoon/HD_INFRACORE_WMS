# ═══════════════════════════════════════════════════════════
# ERP I/F 폴링 — ORDER_H / ORDER_D 미처리분 감지 및 가공
#   ERP 가 push 만 하고 알림은 없으므로 WMS 가 주기적으로 확인한다.
#   WMS_PROC_STAT : R(수신) → S(성공) / E(실패) / V(구버전)
# ═══════════════════════════════════════════════════════════

# 미처리 오더 목록. 가볍게 훑는 감지 쿼리.
SELECT_UNPROCESSED = """
SELECT H.AUFNR,
       MAX(H.IFSEQ)               AS IFSEQ,
       MAX(H.IFDAT + ' ' + H.IFTIM) AS IF_DTM,
       COUNT(D.IFSEQ)             AS detail_cnt
  FROM ORDER_H H
  LEFT JOIN ORDER_D D
         ON D.AUFNR = H.AUFNR
        AND D.IFDAT = H.IFDAT AND D.IFTIM = H.IFTIM
 WHERE H.WMS_PROC_STAT = 'R'
 GROUP BY H.AUFNR
 ORDER BY MAX(H.IFDAT + H.IFTIM)
"""

# 이 오더의 최신 전송회차
#   파라미터 : order_no
SELECT_LATEST_IF = """
SELECT TOP 1 IFSEQ, IFDAT, IFTIM, EQUNR, SEQNO, GSTRS, KMATN
  FROM ORDER_H
 WHERE AUFNR = ?
 ORDER BY IFDAT + IFTIM DESC, IFSEQ DESC
"""

# 착수 여부 — 확정되었거나 피킹이 시작된 오더는 갱신하지 않는다.
#   파라미터 : order_no
COUNT_IN_PROGRESS = """
SELECT COUNT(*)
  FROM pick_table
 WHERE ORDER_NO = ?
   AND LIFECYCLE_STATUS = 'ACTIVE'
   AND (STATUS <> 'WAIT' OR KIT_SEQ IS NOT NULL)
"""

# 기존 피킹라인 무효화 (착수 전에만 호출)
#   파라미터 : order_no
INACTIVE_OLD_PICK = """
UPDATE pick_table
   SET LIFECYCLE_STATUS = 'INACTIVE', UPDATED_DATE = sysdatetime()
 WHERE ORDER_NO = ?
   AND LIFECYCLE_STATUS = 'ACTIVE'
   AND STATUS = 'WAIT'
"""

# ── 가공 : ORDER_D → pick_table ─────────────────────────────
#   ★ 검증 기준값 : 291행 → 팬텀 70 제외 → 221행 → 107행
#     - DUMPS = 'X' 팬텀 제외
#     - GROUP BY (VORNR, MATNR) — 공정 키 누락 시 오답
#     - SUM(BDMNG) 합산, COUNT(*) 는 SRC_LINES 로 보존
#   파라미터 : order_no, ifdat, iftim
INSERT_PICK_FROM_ORDER = """
INSERT INTO pick_table
    (ORDER_NO, ITEM_CODE, ITEM_SEQ, ITEM_NAME,
     REQ_QTY, PICKED_QTY, UOM, SLOC, LPN_TYPE, STATUS, SRC_LINES,
     VORNR, ARBPL, ORDER_H_IFSEQ,
     ENGINE_NO, ENGINE_SEQ_NO, PLAN_DATE, MODEL, LIFECYCLE_STATUS)
SELECT MAX(D.AUFNR),
       D.MATNR,
       MAX(I.seq),
       MAX(D.MAKTX),
       SUM(TRY_CONVERT(int, D.BDMNG)),
       0,
       MAX(D.MEINS),
       MAX(D.LGORT),
       CASE WHEN MAX(CAST(ISNULL(I.washing_yn, 0) AS int)) = 1
            THEN 'W' ELSE 'D' END,
       'WAIT',
       COUNT(*),
       D.VORNR,
       MAX(D.ARBPL),
       ?,
       ?, ?, ?, ?,
       'ACTIVE'
  FROM ORDER_D D
  LEFT JOIN item_master I
         ON I.item_code = D.MATNR AND I.use_yn = 1
 WHERE D.AUFNR = ? AND D.IFDAT = ? AND D.IFTIM = ?
   AND ISNULL(D.DUMPS, '') <> 'X'
 GROUP BY D.VORNR, D.MATNR
"""

# ── 처리 상태 기록 ──────────────────────────────────────────
#   최신 회차만 S, 나머지는 V. 파라미터 : order_no, ifseq
MARK_SUCCESS = """
UPDATE ORDER_H
   SET WMS_PROC_STAT = CASE WHEN IFSEQ = ? THEN 'S' ELSE 'V' END,
       WMS_PROC_DT   = sysdatetime(),
       WMS_ERR_MSG   = NULL
 WHERE AUFNR = ? AND WMS_PROC_STAT = 'R'
"""

MARK_SUCCESS_D = """
UPDATE ORDER_D
   SET WMS_PROC_STAT = CASE WHEN IFDAT = ? AND IFTIM = ? THEN 'S' ELSE 'V' END,
       WMS_PROC_DT   = sysdatetime(),
       WMS_ERR_MSG   = NULL
 WHERE AUFNR = ? AND WMS_PROC_STAT = 'R'
"""

#   파라미터 : err_msg, order_no
MARK_ERROR = """
UPDATE ORDER_H
   SET WMS_PROC_STAT = 'E',
       WMS_PROC_DT   = sysdatetime(),
       WMS_ERR_MSG   = ?
 WHERE AUFNR = ? AND WMS_PROC_STAT = 'R'
"""

SELECT_PROC_LIST = """
SELECT DISTINCT VORNR
  FROM ORDER_D
 WHERE AUFNR = ? AND IFDAT = ? AND IFTIM = ?
   AND ISNULL(DUMPS,'') <> 'X'
"""

UPDATE_PICK_NO = """
UPDATE pick_table
   SET PICK_NO = ?
 WHERE ORDER_NO = ? AND VORNR = ?
   AND LIFECYCLE_STATUS = 'ACTIVE' AND PICK_NO IS NULL
"""