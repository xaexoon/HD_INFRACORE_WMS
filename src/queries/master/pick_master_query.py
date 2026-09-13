# ── 목록 — 공정 단위 ────────────────────────────────────────
#   1행 = 하나의 피킹 JOB = [호기 + 공정 + 서열]
#   ★ 착수예정일(PLAN_DATE)이 오늘 이후인 건만. 지난 건은 처리 완료로 본다.

SELECT_WAIT_LIST = """
SELECT
    P.ORDER_NO,
    P.VORNR              AS PROC_CODE,
    P.PICK_NO,
    MAX(K.KIT_NO)        AS KIT_NO,
    MAX(K.SEQ)           AS KIT_SEQ,
    MAX(K.STATUS)        AS KIT_STATUS,
    MAX(K.DELIVERY_SEQ)  AS DELIVERY_SEQ,
    MAX(P.STATUS)        AS PICK_STATUS,
    MAX(P.SRC_TYPE)      AS SRC_TYPE,
    MAX(P.ENGINE_NO)     AS ENGINE_NO,
    MAX(P.ENGINE_SEQ_NO) AS ENGINE_SEQ_NO,
    MAX(P.PLAN_DATE)     AS PLAN_DATE,
    MAX(M.proc_name)     AS PROC_NAME,
    MAX(M.proc_order)    AS PROC_SORT,
    MAX(P.ARBPL)         AS ARBPL,
    COUNT(*)             AS item_cnt,
    SUM(P.REQ_QTY)       AS total_qty,
    SUM(CASE WHEN P.LPN_TYPE = 'W' THEN 1 ELSE 0 END) AS wash_cnt,
    SUM(CASE WHEN P.LPN_TYPE = 'D' THEN 1 ELSE 0 END) AS dry_cnt,
    SUM(CASE WHEN P.ITEM_SEQ IS NULL THEN 1 ELSE 0 END) AS invalid_cnt,
    MAX(CASE WHEN K.SEQ IS NOT NULL THEN 1 ELSE 0 END)  AS confirmed_yn
FROM pick_table P
LEFT JOIN kit_table K
    ON K.ORDER_NO = P.ORDER_NO AND K.PROC_CODE = P.VORNR
   AND K.LIFECYCLE_STATUS = 'ACTIVE'
LEFT JOIN proc_master M
    ON M.proc_code = P.VORNR AND M.use_yn = 1
WHERE P.STATUS IN ('WAIT','ISSUED')
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
  AND P.PLAN_DATE >= CONVERT(char(10), GETDATE(), 23)
GROUP BY P.ORDER_NO, P.VORNR, P.PICK_NO
ORDER BY MAX(P.PLAN_DATE),
         CASE WHEN MAX(K.DELIVERY_SEQ) IS NULL THEN 1 ELSE 0 END,
         MAX(K.DELIVERY_SEQ),
         P.PICK_NO
"""

# ── 하위 자재 [보기] ────────────────────────────────────────
#   파라미터 : pick_no
SELECT_ITEMS = """
SELECT
    P.SEQ, P.PICK_NO, P.SRC_TYPE,
    P.ITEM_CODE, P.ITEM_NAME, P.ITEM_SEQ,
    P.REQ_QTY, P.PICKED_QTY, P.UOM, P.SLOC, P.LPN_TYPE, P.SRC_LINES,
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
WHERE P.PICK_NO = ?
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
ORDER BY P.LPN_TYPE, P.ITEM_CODE
"""


# ── 확정 전 검증 — 마스터 미등록 ────────────────────────────
#   파라미터 : pick_no
SELECT_INVALID = """
SELECT P.SEQ, P.ITEM_CODE, P.ITEM_NAME,
       CASE WHEN P.ITEM_SEQ IS NULL THEN 'NO_ITEM' ELSE 'NO_PROC' END AS reason
FROM pick_table P
LEFT JOIN proc_master M
    ON M.proc_code = P.VORNR AND M.use_yn = 1
WHERE P.PICK_NO = ?
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
  AND (P.ITEM_SEQ IS NULL OR M.seq IS NULL)
"""


# ── 확정 전 재고 검증 ───────────────────────────────────────
#   부족한 자재만 반환. 빈 결과면 확정 가능.
#   파라미터 : pick_no
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
WHERE P.PICK_NO = ?
  AND P.STATUS = 'WAIT'
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
  AND ISNULL(S.stock_qty, 0) < P.REQ_QTY
"""


# ── 확정 ────────────────────────────────────────────────────
#   중복 확정 방지. UX_kit_active 가 최후 방어지만
#   친절한 메시지를 위해 먼저 확인한다.
#   파라미터 : pick_no
CHECK_KIT_EXISTS = """
SELECT K.SEQ, K.KIT_NO, K.STATUS
  FROM kit_table K
 WHERE K.LIFECYCLE_STATUS = 'ACTIVE'
   AND EXISTS (SELECT 1 FROM pick_table P
                WHERE P.PICK_NO = ?
                  AND P.ORDER_NO = K.ORDER_NO
                  AND P.VORNR    = K.PROC_CODE)
"""

#   파라미터 : pick_no
SELECT_PICK_TARGET = """
SELECT SEQ, ITEM_SEQ, REQ_QTY, PLAN_DATE
  FROM pick_table
 WHERE PICK_NO = ?
   AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# kit_table 생성
#   파라미터 : kit_no, pick_no
INSERT_KIT = """
INSERT INTO kit_table
    (KIT_NO, ORDER_NO, ENGINE_SEQ_NO, ENGINE_NO, MODEL, PLAN_DATE,
     PROC_CODE, PROC_SORT, WORK_CENTER, WORK_CENTER_NM,
     DELIVERY_SEQ, STATUS, HOLD_YN, LIFECYCLE_STATUS, SRC_ORDER_H_SEQ)
OUTPUT INSERTED.SEQ, INSERTED.KIT_NO
SELECT TOP 1
       ?, P.ORDER_NO, P.ENGINE_SEQ_NO, P.ENGINE_NO, P.MODEL, P.PLAN_DATE,
       P.VORNR, ISNULL(M.proc_order, 0), P.ARBPL, M.proc_name,
       ?, 'WAIT', 0, 'ACTIVE', P.ORDER_H_IFSEQ
  FROM pick_table P
  LEFT JOIN proc_master M
    ON M.proc_code = P.VORNR AND M.use_yn = 1
 WHERE P.PICK_NO = ?
   AND P.STATUS = 'WAIT'
   AND P.LIFECYCLE_STATUS = 'ACTIVE'
"""

# 확정 후 상태 전이
#   파라미터 : kit_seq, pick_no
ISSUE_PICK = """
UPDATE pick_table
   SET KIT_SEQ = ?, STATUS = 'ISSUED', UPDATED_DATE = SYSDATETIME()
 WHERE PICK_NO = ?
   AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""


# ── 확정 대기 목록의 하위 자재 (일괄) ───────────────────────
SELECT_WAIT_ITEMS_ALL = """
SELECT
    P.SEQ, P.ORDER_NO, P.VORNR, P.PICK_NO, P.SRC_TYPE,
    P.ITEM_CODE, P.ITEM_NAME, P.ITEM_SEQ,
    P.REQ_QTY, P.PICKED_QTY, P.UOM, P.SLOC, P.LPN_TYPE, P.SRC_LINES,
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
WHERE P.STATUS IN ('WAIT','ISSUED')
  AND P.LIFECYCLE_STATUS = 'ACTIVE'
  AND P.PLAN_DATE >= CONVERT(char(10), GETDATE(), 23)
ORDER BY P.ORDER_NO, P.VORNR, P.LPN_TYPE, P.ITEM_CODE
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
#   피킹이 한 건이라도 시작됐으면 취소 불가.
#   담당자 확정 : 피킹/키팅이 진행된 오더는 변경 불가.
#   파라미터 : kit_seq
COUNT_PICK_STARTED = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ?
   AND (PICKED_QTY > 0 OR STATUS <> 'ISSUED')
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# W/D-LPN 이 발행되었으면 취소 불가.
#   파라미터 : kit_seq
COUNT_KIT_LPN_USED = """
SELECT COUNT(*) FROM lpn_master
 WHERE kit_seq = ? AND lpn_type IN ('W','D')
   AND lifecycle_status = 'ACTIVE'
"""

# 긴급 보충이 붙어 있으면 확정 취소 불가.
# 긴급분은 확정 단계를 건너뛴 지시라 WAIT 으로 되돌리면 소속 키팅을 잃는다.
#   파라미터 : kit_seq
COUNT_EMERGENCY_ATTACHED = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ? AND SRC_TYPE = 'URGENT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""


#   파라미터 : kit_seq
CANCEL_TXN_PLAN = """
UPDATE lpn_txn
   SET status = 'CANCEL'
 WHERE status = 'PLAN'
   AND PICK_SEQ IN (SELECT SEQ FROM pick_table WHERE KIT_SEQ = ?)
"""

# 취소 시 CANCEL 이 아니라 WAIT 으로 복귀시킨다.
# 재확정이 가능해야 하기 때문.
#   파라미터 : kit_seq
RESET_PICK = """
UPDATE pick_table
   SET KIT_SEQ = NULL, STATUS = 'WAIT', UPDATED_DATE = SYSDATETIME()
 WHERE KIT_SEQ = ?
   AND STATUS = 'ISSUED'
   AND PICKED_QTY = 0
"""

# UX_kit_active 가 ACTIVE 만 보므로 INACTIVE 로 죽여야 재확정이 가능하다.
#   파라미터 : kit_seq
INACTIVE_KIT = """
UPDATE kit_table
   SET STATUS = 'CANCEL', LIFECYCLE_STATUS = 'INACTIVE',
       UPDATED_DATE = SYSDATETIME()
 WHERE SEQ = ? AND STATUS = 'WAIT'
"""


# ═══════════════════════════════════════════════════════════
# 긴급 피킹
#   불량·파손으로 부족분이 생겼을 때 기존 키팅에 자재를 보충한다.
#   새 kit_table 을 만들지 않고 기존 KIT_SEQ 에 붙인다.
#   (같은 W/D-LPN 에 담겨야 최종 K-LPN 하나로 나가기 때문)
# ═══════════════════════════════════════════════════════════

# 긴급 피킹 대상 피킹리스트. 확정된 것만.
SELECT_KIT_LIST_FOR_EMERGENCY = """
SELECT k.SEQ AS kit_seq, k.KIT_NO, k.ORDER_NO, k.PROC_CODE,
       k.ENGINE_NO, k.ENGINE_SEQ_NO, k.WORK_CENTER_NM, k.PLAN_DATE,
       k.DELIVERY_SEQ,
       k.STATUS, k.W_LPN_SEQ, k.D_LPN_SEQ,
       MAX(p.PICK_NO)  AS PICK_NO,
       COUNT(p.SEQ)    AS item_cnt
  FROM kit_table k
  LEFT JOIN pick_table p ON p.KIT_SEQ = k.SEQ AND p.LIFECYCLE_STATUS = 'ACTIVE'
 WHERE k.LIFECYCLE_STATUS = 'ACTIVE'
 GROUP BY k.SEQ, k.KIT_NO, k.ORDER_NO, k.PROC_CODE,
          k.ENGINE_NO, k.ENGINE_SEQ_NO, k.WORK_CENTER_NM, k.PLAN_DATE,
          k.DELIVERY_SEQ,
          k.STATUS, k.W_LPN_SEQ, k.D_LPN_SEQ
 ORDER BY k.ENGINE_SEQ_NO, k.DELIVERY_SEQ
"""

# 그 피킹리스트의 자재 + 가용재고
#   파라미터 : kit_seq
SELECT_ITEM_FOR_EMERGENCY = """
SELECT p.SEQ AS pick_seq, p.PICK_NO, p.SRC_TYPE,
       p.ITEM_CODE, p.ITEM_NAME, p.ITEM_SEQ,
       p.UOM, p.REQ_QTY, p.PICKED_QTY, p.LPN_TYPE, p.STATUS,
       ISNULL(s.stock_qty, 0) AS stock_qty
  FROM pick_table p
  OUTER APPLY (
      SELECT SUM(v.available_qty) AS stock_qty
        FROM V_LPN_ALLOCATABLE v
       WHERE v.item_seq = p.ITEM_SEQ
         AND v.lpn_type = 'R' AND v.process_status = 'AVAILABLE'
  ) s
 WHERE p.KIT_SEQ = ? AND p.LIFECYCLE_STATUS = 'ACTIVE'
 ORDER BY CASE WHEN p.LPN_TYPE = 'W' THEN 0 ELSE 1 END, p.ITEM_CODE
"""

# 원본 피킹라인 — 복사할 값
#   파라미터 : pick_seq
SELECT_PICK_FOR_EMERGENCY = """
SELECT p.SEQ, p.KIT_SEQ, p.ORDER_NO, p.ITEM_CODE, p.ITEM_SEQ, p.ITEM_NAME,
       p.UOM, p.SLOC, p.LPN_TYPE, p.VORNR, p.ARBPL, p.ORDER_H_IFSEQ,
       p.ENGINE_NO, p.ENGINE_SEQ_NO, p.PLAN_DATE, p.MODEL,
       k.STATUS AS kit_status, k.HOLD_YN, k.LIFECYCLE_STATUS AS kit_life,
       k.W_LPN_SEQ, k.D_LPN_SEQ
  FROM pick_table p
  JOIN kit_table  k ON k.SEQ = p.KIT_SEQ
 WHERE p.SEQ = ? AND p.LIFECYCLE_STATUS = 'ACTIVE'
"""

# 긴급 지시 생성. 확정 단계를 건너뛰고 바로 ISSUED 로 넣는다.
#   기존 키팅에 붙는 것이라 별도 확정이 불필요하기 때문.
#   파라미터 : pick_no, src_pick_seq, kit_seq, order_no,
#              item_code, item_seq, item_name, req_qty,
#              uom, sloc, lpn_type, vornr, arbpl, order_h_ifseq,
#              engine_no, engine_seq_no, plan_date, model, remark
INSERT_EMERGENCY_PICK = """
INSERT INTO pick_table
    (PICK_NO, SRC_TYPE, SRC_PICK_SEQ, KIT_SEQ, ORDER_NO,
     ITEM_CODE, ITEM_SEQ, ITEM_NAME,
     REQ_QTY, PICKED_QTY, UOM, SLOC, LPN_TYPE, STATUS, SRC_LINES,
     VORNR, ARBPL, ORDER_H_IFSEQ,
     ENGINE_NO, ENGINE_SEQ_NO, PLAN_DATE, MODEL, REMARK, LIFECYCLE_STATUS)
OUTPUT INSERTED.SEQ
VALUES (?, 'URGENT', ?, ?, ?,
        ?, ?, ?,
        ?, 0, ?, ?, ?, 'ISSUED', 0,
        ?, ?, ?,
        ?, ?, ?, ?, ?, 'ACTIVE')
"""

# 이미 발행된 W/D-LPN 에 담길 수량 합산.
#   UQ_LPN_DETAIL 때문에 새 행을 못 넣으므로 init_qty 를 늘린다.
#   파라미터 : qty, lpn_master_seq, item_seq
ADD_LPN_DETAIL_QTY = """
UPDATE lpn_detail
   SET init_qty = init_qty + ?, updated_date = sysdatetime()
 WHERE lpn_master_seq = ? AND item_seq = ?
"""

# 해당 자재가 아직 용기에 없으면 새로 넣는다.
#   파라미터 : lpn_master_seq, item_seq, qty
INSERT_LPN_DETAIL_ONE = """
INSERT INTO lpn_detail (lpn_master_seq, item_seq, init_qty, current_qty)
VALUES (?, ?, ?, 0)
"""


# ═══════════════════════════════════════════════════════════
# 수동 피킹리스트 등록
#   ERP 장애로 지시가 안 내려올 때 현장 작업을 이어가기 위한 비상 수단.
#   BOM 이 ERP 에만 있으므로 자재를 사람이 직접 입력한다.
#   SRC_TYPE = 'MANUAL' 로 정상 수신분(ERP)·긴급 보충분(URGENT)과 구분.
# ═══════════════════════════════════════════════════════════

# 동일 [오더 + 공정] 이 이미 있는가
#   파라미터 : order_no, vornr
CHECK_PICK_EXISTS = """
SELECT TOP 1 PICK_NO, SRC_TYPE, STATUS
  FROM pick_table
 WHERE ORDER_NO = ? AND VORNR = ?
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 자재마스터 조회 — 입력한 자재코드 검증
#   파라미터 : item_code
SELECT_ITEM_BY_CODE = """
SELECT seq, item_code, item_name, uom, washing_yn
  FROM item_master
 WHERE item_code = ? AND use_yn = 1
"""

# 자재 검색 (자동완성)
#   파라미터 : keyword x 2
SEARCH_ITEM = """
SELECT TOP 30 seq, item_code, item_name, uom, washing_yn
  FROM item_master
 WHERE use_yn = 1
   AND (item_code LIKE ? OR item_name LIKE ?)
 ORDER BY item_code
"""

# 수동 지시 생성
#   파라미터 : pick_no, order_no, item_code, item_seq, item_name,
#              req_qty, uom, sloc, lpn_type, vornr, arbpl,
#              engine_no, engine_seq_no, plan_date, remark
INSERT_MANUAL_PICK = """
INSERT INTO pick_table
    (PICK_NO, SRC_TYPE, ORDER_NO,
     ITEM_CODE, ITEM_SEQ, ITEM_NAME,
     REQ_QTY, PICKED_QTY, UOM, SLOC, LPN_TYPE, STATUS, SRC_LINES,
     VORNR, ARBPL, ORDER_H_IFSEQ,
     ENGINE_NO, ENGINE_SEQ_NO, PLAN_DATE, REMARK, LIFECYCLE_STATUS)
OUTPUT INSERTED.SEQ
VALUES (?, 'MANUAL', ?,
        ?, ?, ?,
        ?, 0, ?, ?, ?, 'WAIT', 1,
        ?, ?, NULL,
        ?, ?, ?, ?, 'ACTIVE')
"""

# ── 긴급 피킹 취소 ──────────────────────────────────────────
#   스캔 전에만 가능. 실물이 나갔으면 반납 절차가 필요하므로 차단한다.

#   파라미터 : pick_seq
SELECT_EMERGENCY_FOR_CANCEL = """
SELECT p.SEQ, p.PICK_NO, p.SRC_TYPE, p.KIT_SEQ, p.ITEM_SEQ, p.ITEM_CODE,
       p.REQ_QTY, p.PICKED_QTY, p.STATUS, p.LPN_TYPE, p.LIFECYCLE_STATUS,
       k.STATUS AS kit_status, k.HOLD_YN,
       k.W_LPN_SEQ, k.D_LPN_SEQ
  FROM pick_table p
  JOIN kit_table  k ON k.SEQ = p.KIT_SEQ
 WHERE p.SEQ = ?
"""

# 예약 해제
#   파라미터 : pick_seq
CANCEL_EMERGENCY_TXN = """
UPDATE lpn_txn
   SET status = 'CANCEL'
 WHERE PICK_SEQ = ? AND txn_type = 'PK' AND status = 'PLAN'
"""

# 용기에 늘려둔 수량 되돌리기
#   파라미터 : qty, lpn_master_seq, item_seq
SUB_LPN_DETAIL_QTY = """
UPDATE lpn_detail
   SET init_qty = CASE WHEN init_qty - ? < current_qty
                       THEN current_qty ELSE init_qty - ? END,
       updated_date = sysdatetime()
 WHERE lpn_master_seq = ? AND item_seq = ?
"""

# 긴급 지시 무효화. 행은 남기고 INACTIVE 로 (이력 보존)
#   파라미터 : pick_seq
INACTIVE_EMERGENCY_PICK = """
UPDATE pick_table
   SET STATUS = 'CANCEL', LIFECYCLE_STATUS = 'INACTIVE',
       UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND SRC_TYPE = 'URGENT'
   AND STATUS = 'ISSUED' AND PICKED_QTY = 0
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""


# ═══════════════════════════════════════════════════════════
# 피킹리스트 분할
#   자재가 많아 한 용기에 담기 어려울 때 지시를 둘로 나눈다.
#   확정 전에만 가능 — 확정 후에는 kit_table·W/D-LPN·PLAN 까지
#   따라가야 해서 되돌리기 어렵다.
#
#   분할본은 호기·서열은 같고 공정만 +1 (30 → 31).
#   이미 쓰는 번호면 빈 번호를 찾아 올린다.
#
#   ※ 원본에 최소 1개는 남겨야 한다.
#     전량 분할을 허용하면 REQ_QTY = 0 행이 생겨 CK_PICK_QTY 위반.
# ═══════════════════════════════════════════════════════════

# 분할 대상 지시 — 확정 여부까지 확인
#   파라미터 : pick_no
SELECT_PICK_FOR_SPLIT = """
SELECT p.SEQ, p.PICK_NO, p.SRC_TYPE, p.KIT_SEQ,
       p.ORDER_NO, p.VORNR, p.ARBPL, p.ORDER_H_IFSEQ,
       p.ENGINE_NO, p.ENGINE_SEQ_NO, p.PLAN_DATE, p.MODEL,
       p.ITEM_CODE, p.ITEM_SEQ, p.ITEM_NAME, p.UOM, p.SLOC,
       p.REQ_QTY, p.PICKED_QTY, p.LPN_TYPE, p.STATUS, p.SRC_LINES
  FROM pick_table p
 WHERE p.PICK_NO = ? AND p.LIFECYCLE_STATUS = 'ACTIVE'
 ORDER BY p.SEQ
"""

# 빈 공정번호 찾기 — base+1 부터 위로
#   파라미터 : order_no, vornr_base
NEXT_SPLIT_VORNR = """
SELECT TOP 1 n.v
  FROM (SELECT CAST(? AS int) + ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS v
          FROM sys.all_objects) n
 WHERE NOT EXISTS (
       SELECT 1 FROM pick_table p
        WHERE p.ORDER_NO = ?
          AND p.VORNR = CAST(n.v AS varchar(20))
          AND p.LIFECYCLE_STATUS = 'ACTIVE'
   )
 ORDER BY n.v
"""

# 원본 수량 차감. 최소 1개는 남긴다.
#   파라미터 : qty, pick_seq, qty
SUB_SPLIT_QTY = """
UPDATE pick_table
   SET REQ_QTY = REQ_QTY - ?, UPDATED_DATE = sysdatetime()
 WHERE SEQ = ?
   AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
   AND REQ_QTY - ? >= 1
"""

# 분할본 생성
#   파라미터 : pick_no, src_pick_seq, order_no, item_code, item_seq, item_name,
#              req_qty, uom, sloc, lpn_type, vornr, arbpl, order_h_ifseq,
#              engine_no, engine_seq_no, plan_date, model, remark
INSERT_SPLIT_PICK = """
INSERT INTO pick_table
    (PICK_NO, SRC_TYPE, SRC_PICK_SEQ, ORDER_NO,
     ITEM_CODE, ITEM_SEQ, ITEM_NAME,
     REQ_QTY, PICKED_QTY, UOM, SLOC, LPN_TYPE, STATUS, SRC_LINES,
     VORNR, ARBPL, ORDER_H_IFSEQ,
     ENGINE_NO, ENGINE_SEQ_NO, PLAN_DATE, MODEL, REMARK, LIFECYCLE_STATUS)
OUTPUT INSERTED.SEQ
VALUES (?, 'SPLIT', ?, ?,
        ?, ?, ?,
        ?, 0, ?, ?, ?, 'WAIT', 1,
        ?, ?, ?,
        ?, ?, ?, ?, ?, 'ACTIVE')
"""

# 분할 공정을 마스터에 등록. 모델·ERP공정·순서는 원본 공정 행에서 물려받는다
#   (pick_table.MODEL 이 비어 있는 건이 있어 지시에서는 모델을 얻을 수 없다)
#   파라미터 : proc_code, proc_name, base_proc_code, proc_code
INSERT_PROC_IF_MISSING = """
INSERT INTO proc_master
    (model, erp_code, proc_code, proc_name, proc_order, src_type, use_yn)
SELECT TOP 1 m.model, m.erp_code, ?, ?, m.proc_order, 'SPLIT', 1
  FROM proc_master m
 WHERE m.proc_code = ? AND m.use_yn = 1
   AND NOT EXISTS (SELECT 1 FROM proc_master x
                    WHERE x.model = m.model AND x.proc_code = ? AND x.use_yn = 1)
"""



# ── 분할 취소 ───────────────────────────────────────────────
#   확정 전에만 가능. 확정 후라면 먼저 확정 취소를 해야 한다.
#   분할본 행은 INACTIVE 로 죽이고 원본 수량을 복원한다.

#   파라미터 : pick_no
SELECT_SPLIT_FOR_CANCEL = """
SELECT p.SEQ, p.PICK_NO, p.SRC_TYPE, p.SRC_PICK_SEQ, p.KIT_SEQ,
       p.ORDER_NO, p.VORNR, p.ITEM_CODE, p.ITEM_NAME,
       p.REQ_QTY, p.PICKED_QTY, p.STATUS, p.LIFECYCLE_STATUS,
       s.SEQ    AS src_seq,
       s.PICK_NO AS src_pick_no,
       s.VORNR  AS src_vornr,
       s.REQ_QTY AS src_req_qty,
       s.STATUS  AS src_status,
       s.KIT_SEQ AS src_kit_seq,
       s.LIFECYCLE_STATUS AS src_life
  FROM pick_table p
  LEFT JOIN pick_table s ON s.SEQ = p.SRC_PICK_SEQ
 WHERE p.PICK_NO = ? AND p.LIFECYCLE_STATUS = 'ACTIVE'
 ORDER BY p.SEQ
"""

# 원본 수량 복원
#   파라미터 : qty, src_seq
ADD_SPLIT_QTY_BACK = """
UPDATE pick_table
   SET REQ_QTY = REQ_QTY + ?, UPDATED_DATE = sysdatetime()
 WHERE SEQ = ?
   AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 분할본 무효화. 행은 남겨 이력을 보존한다.
#   파라미터 : pick_seq
INACTIVE_SPLIT_PICK = """
UPDATE pick_table
   SET STATUS = 'CANCEL', LIFECYCLE_STATUS = 'INACTIVE',
       UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND SRC_TYPE = 'SPLIT'
   AND STATUS = 'WAIT' AND PICKED_QTY = 0
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 분할로 생긴 공정이 더 이상 안 쓰이면 마스터에서 제거
#   파라미터 : vornr, vornr
DELETE_PROC_IF_UNUSED = """
DELETE FROM proc_master
 WHERE proc_code = ? AND src_type = 'SPLIT'
   AND NOT EXISTS (SELECT 1 FROM pick_table
                    WHERE VORNR = ? AND LIFECYCLE_STATUS = 'ACTIVE')
"""


