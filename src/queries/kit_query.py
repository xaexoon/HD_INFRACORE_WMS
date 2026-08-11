# ═══════════════════════════════════════════════════════════
# 키팅 지시 발행
#   W/D-LPN 바인딩 완료 → kit_table WAIT → ISSUED
#   발행 조건은 "둘 다 있냐" 가 아니라 "필요한 게 다 됐냐".
#   W_LPN_SEQ 가 NULL 이면 세척 자재가 없는 공정이므로 기다리지 않는다.
# ═══════════════════════════════════════════════════════════

# 발행 가능 여부 판정용 헤더
#   파라미터 : kit_seq
SELECT_KIT_STATE = """
SELECT k.SEQ, k.ORDER_NO, k.PROC_CODE, k.ENGINE_NO, k.ENGINE_SEQ_NO,
       k.STATUS, k.HOLD_YN, k.LIFECYCLE_STATUS,
       k.W_LPN_SEQ, k.D_LPN_SEQ,
       w.process_status AS w_status, w.location_seq AS w_loc, w.lpn_code AS w_code,
       d.process_status AS d_status, d.location_seq AS d_loc, d.lpn_code AS d_code
  FROM kit_table k
  LEFT JOIN lpn_master w ON w.seq = k.W_LPN_SEQ
  LEFT JOIN lpn_master d ON d.seq = k.D_LPN_SEQ
 WHERE k.SEQ = ?
"""

# 미완료 피킹 잔량
#   파라미터 : kit_seq
COUNT_PICK_NOT_PICKED = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ? AND STATUS <> 'PICKED'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 발행
#   파라미터 : kit_seq
ISSUE_KIT = """
UPDATE kit_table
   SET STATUS = 'ISSUED', UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND STATUS = 'WAIT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 발행 취소 (키팅 착수 전)
CANCEL_ISSUE_KIT = """
UPDATE kit_table
   SET STATUS = 'WAIT', UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND STATUS = 'ISSUED'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""


# ── 발행 대기 목록 (관리 화면) ──────────────────────────────
#   ready_yn : 지금 발행 가능한가
SELECT_KIT_WAIT_LIST = """
SELECT k.SEQ AS kit_seq, k.ORDER_NO, k.PROC_CODE, k.WORK_CENTER_NM,
       k.ENGINE_NO, k.ENGINE_SEQ_NO, k.PLAN_DATE, k.DELIVERY_SEQ,
       k.STATUS, k.HOLD_YN,
       k.W_LPN_SEQ, k.D_LPN_SEQ,
       w.lpn_code AS w_lpn_code, w.process_status AS w_status,
       wl.location_code AS w_location,
       d.lpn_code AS d_lpn_code, d.process_status AS d_status,
       dl.location_code AS d_location,
       p.total_cnt, p.picked_cnt,
       CASE WHEN k.HOLD_YN = 1 THEN 0
            WHEN p.total_cnt <> p.picked_cnt THEN 0
            WHEN k.W_LPN_SEQ IS NOT NULL AND w.process_status <> 'WASH_COMP' THEN 0
            WHEN k.D_LPN_SEQ IS NOT NULL AND d.location_seq IS NULL THEN 0
            ELSE 1 END AS ready_yn
  FROM kit_table k
  LEFT JOIN lpn_master w  ON w.seq = k.W_LPN_SEQ
  LEFT JOIN location_master wl ON wl.seq = w.location_seq
  LEFT JOIN lpn_master d  ON d.seq = k.D_LPN_SEQ
  LEFT JOIN location_master dl ON dl.seq = d.location_seq
  CROSS APPLY (
      SELECT COUNT(*) AS total_cnt,
             SUM(CASE WHEN STATUS = 'PICKED' THEN 1 ELSE 0 END) AS picked_cnt
        FROM pick_table
       WHERE KIT_SEQ = k.SEQ AND LIFECYCLE_STATUS = 'ACTIVE'
  ) p
 WHERE k.STATUS = 'WAIT'
   AND k.LIFECYCLE_STATUS = 'ACTIVE'
 ORDER BY k.ENGINE_SEQ_NO, k.DELIVERY_SEQ
"""


# ── 태블릿 키팅 작업 목록 ───────────────────────────────────
#   발행된 건만. 완료분도 진행률 표시를 위해 포함.
SELECT_KIT_ISSUED_LIST = """
SELECT k.SEQ AS kit_seq, k.ORDER_NO, k.PROC_CODE, k.WORK_CENTER_NM,
       k.ENGINE_NO, k.ENGINE_SEQ_NO, k.DELIVERY_SEQ, k.STATUS,
       k.W_LPN_SEQ, k.D_LPN_SEQ, k.K_LPN_SEQ,
       w.lpn_code AS w_lpn_code, wl.location_code AS w_location,
       d.lpn_code AS d_lpn_code, dl.location_code AS d_location,
       kl.lpn_code AS k_lpn_code
  FROM kit_table k
  LEFT JOIN lpn_master w  ON w.seq = k.W_LPN_SEQ
  LEFT JOIN location_master wl ON wl.seq = w.location_seq
  LEFT JOIN lpn_master d  ON d.seq = k.D_LPN_SEQ
  LEFT JOIN location_master dl ON dl.seq = d.location_seq
  LEFT JOIN lpn_master kl ON kl.seq = k.K_LPN_SEQ
 WHERE k.STATUS IN ('ISSUED','KITTED')
   AND k.LIFECYCLE_STATUS = 'ACTIVE'
   AND k.HOLD_YN = 0
 ORDER BY k.ENGINE_SEQ_NO, k.DELIVERY_SEQ
"""

# 키팅 1건 상세 — 담긴 자재 목록
#   파라미터 : kit_seq
SELECT_KIT_ITEMS = """
SELECT p.SEQ AS pick_seq, p.ITEM_CODE, p.ITEM_NAME, p.UOM,
       p.REQ_QTY, p.PICKED_QTY, p.LPN_TYPE, p.STATUS,
       m.lpn_code, l.location_code
  FROM pick_table p
  JOIN kit_table k ON k.SEQ = p.KIT_SEQ
  LEFT JOIN lpn_master m
         ON m.seq = CASE WHEN p.LPN_TYPE = 'W' THEN k.W_LPN_SEQ
                         ELSE k.D_LPN_SEQ END
  LEFT JOIN location_master l ON l.seq = m.location_seq
 WHERE p.KIT_SEQ = ? AND p.LIFECYCLE_STATUS = 'ACTIVE'
 ORDER BY CASE WHEN p.LPN_TYPE = 'W' THEN 0 ELSE 1 END, p.ITEM_CODE
"""