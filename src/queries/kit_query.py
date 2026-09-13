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
 WHERE SEQ = ? AND STATUS IN ('WAIT','PICKING')
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
 WHERE k.STATUS IN ('ISSUED','KITTING')
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


SELECT_KIT_DETAIL = """
SELECT d.item_seq, SUM(d.current_qty) AS qty
  FROM lpn_detail d
 WHERE d.lpn_master_seq IN (?, ?)
   AND d.current_qty > 0
 GROUP BY d.item_seq
"""

INSERT_K_LPN = """
INSERT INTO lpn_master
    (lpn_code, lpn_type, process_status, lifecycle_status,
     print_yn, split_yn, kit_seq, order_no, engine_no, proc_code, engine_seq_no)
OUTPUT INSERTED.seq
VALUES (?, 'K', 'CREATED', 'ACTIVE', 0, 0, ?, ?, ?, ?, ?)
"""

INSERT_K_DETAIL = """
INSERT INTO lpn_detail (lpn_master_seq, item_seq, init_qty, current_qty)
VALUES (?, ?, ?, ?)
"""

# W/D-LPN 소멸. 수량은 K-LPN 으로 넘어갔으므로 0 으로.
#   파라미터 : lpn_master_seq
CONSUME_SRC_LPN = """
UPDATE lpn_master
   SET process_status   = 'CONSUMED',
       lifecycle_status = 'INACTIVE',
       updated_date     = sysdatetime()
 WHERE seq = ?
"""

CLEAR_SRC_DETAIL = """
UPDATE lpn_detail
   SET current_qty = 0, updated_date = sysdatetime()
 WHERE lpn_master_seq = ?
"""

# 통합 이력. 파라미터 : k_lpn_seq, device_id, worker_id, src_lpn_seq
INSERT_TXN_MERGE = """
INSERT INTO lpn_txn
      (txn_type, status, lpn_master_seq, to_lpn_seq, item_seq, qty,
       from_location_seq, device_id, worker_id)
SELECT 'KT', 'DONE', d.lpn_master_seq, ?, d.item_seq, d.current_qty,
       m.location_seq, ?, ?
  FROM lpn_detail d
  JOIN lpn_master m ON m.seq = d.lpn_master_seq
 WHERE d.lpn_master_seq = ? AND d.current_qty > 0
"""

# 키팅 완료
UPDATE_KIT_DONE = """
UPDATE kit_table
   SET K_LPN_SEQ = ?, STATUS = 'KITTED', UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND STATUS IN ('ISSUED','KITTING')
"""


# ═══════════════════════════════════════════════════════════
# 스테이션 배정
#   K-LPN 은 STATION_NO 없이 CREATED 로 먼저 만들어진다.
#   ACS 가 번호를 지정해 주면 채워지고, 그때부터 RFID 목록 대상이 된다.
#
#   K-LPN 을 먼저 만들고 ACS 에 물어보는 순서인 이유
#     반대로 하면(ACS 먼저 -> INSERT) 그 사이 장애 시 ACS 는 스테이션을
#     내줬는데 WMS 에는 기록이 없는 상태가 된다. 그 자리가 유령 점유되고
#     조회할 방법조차 없다. 우리 기록을 항상 먼저 남긴다.
# ═══════════════════════════════════════════════════════════

# 스테이션 배정.  파라미터 : station_no, station_name, lpn_code
#   배정 여부는 상태값이 아니라 STATION_NO 로 판단한다.
#   process_status 는 AMR 호출 진행(CREATED -> CALLED -> ...)을 나타내는 축이라
#   스테이션 배정과 섞지 않는다.
ASSIGN_STATION_BY_LPN = """
UPDATE k
   SET k.STATION_NO   = ?,
       k.STATION_NAME = ?,
       k.UPDATED_DATE = sysdatetime()
  FROM kit_table k
  JOIN lpn_master m ON m.kit_seq = k.SEQ
 WHERE m.lpn_code = ? AND m.lpn_type = 'K'
   AND k.STATION_NO IS NULL
"""

# ═══════════════════════════════════════════════════════════
# AMR 호출 상태
#   CREATED -> CALLED -> ACCEPTED -> RUNNING -> COMPLETED
#   CREATED/CALLED 는 WMS 가, 그 뒤는 ACS 가 2-1 로 알려준다.
# ═══════════════════════════════════════════════════════════

# 상태 변경.  파라미터 : to_status, lpn_code, to_status
#   같은 상태가 다시 오면 0건이 되어 이력이 중복으로 쌓이지 않는다.
UPDATE_KLPN_CALL_STATUS = """
UPDATE lpn_master
   SET process_status = ?, updated_date = sysdatetime()
 WHERE lpn_code = ? AND lpn_type = 'K'
   AND lifecycle_status = 'ACTIVE'
   AND process_status <> ?
"""

# 상태 이력을 남길 때 쓴다.  파라미터 : lpn_code
SELECT_KLPN_SEQ = """
SELECT seq, process_status FROM lpn_master
 WHERE lpn_code = ? AND lpn_type = 'K'
"""


# 스테이션을 못 받은 K-LPN 중 가장 오래된 1건.
#   TOP 1 인 이유 : 스테이션은 한정 자원이다. 여러 건을 한꺼번에 요청하면
#   늦게 만들어진 K-LPN 이 먼저 자리를 차지할 수 있다.
#   한 건씩 배정하고 다음 주기에 다음 건으로 넘어간다.
SELECT_KLPN_NO_STATION = """
SELECT TOP 1
       m.seq        AS k_lpn_seq,
       m.lpn_code   AS k_lpn_code,
       k.SEQ        AS kit_seq,
       k.ENGINE_NO,
       k.PROC_CODE
  FROM lpn_master m
  JOIN kit_table  k ON k.SEQ = m.kit_seq
 WHERE m.lpn_type = 'K'
   AND m.process_status = 'CREATED'
   AND m.lifecycle_status = 'ACTIVE'
   AND k.STATION_NO IS NULL
 ORDER BY m.created_date, m.seq
"""


#   파라미터 : lpn_code
SELECT_SCAN_LPN = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status, m.lifecycle_status,
       m.location_seq, m.kit_seq,
       m.order_no, m.engine_no, m.proc_code, m.engine_seq_no
  FROM lpn_master m
 WHERE m.lpn_code = ?
"""

INSERT_VERIFY_LOG = """
INSERT INTO kit_verify_log
      (kit_seq, lpn_master_seq, scan_code,
       verify_seq_yn, verify_proc_yn, verify_stat_yn,
       result, fail_reason, device_id, worker_id)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# 이 키팅의 검증 이력
#   파라미터 : kit_seq
SELECT_VERIFY_LOG = """
SELECT v.seq, v.scan_code, v.verify_seq_yn, v.verify_proc_yn, v.verify_stat_yn,
       v.result, v.fail_reason, v.device_id, v.worker_id, v.verify_date,
       m.lpn_type
  FROM kit_verify_log v
  LEFT JOIN lpn_master m ON m.seq = v.lpn_master_seq
 WHERE v.kit_seq = ?
 ORDER BY v.verify_date DESC, v.seq DESC
"""

# 필요한 용기가 전부 PASS 되었는가
#   파라미터 : kit_seq
COUNT_VERIFY_PASS = """
SELECT COUNT(DISTINCT v.lpn_master_seq)
  FROM kit_verify_log v
 WHERE v.kit_seq = ? AND v.result = 'PASS'
   AND v.lpn_master_seq IN
       (SELECT W_LPN_SEQ FROM kit_table WHERE SEQ = ?
        UNION ALL
        SELECT D_LPN_SEQ FROM kit_table WHERE SEQ = ?)
"""

# 키팅 착수
START_KITTING = """
UPDATE kit_table
   SET STATUS = 'KITTING', UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND STATUS = 'ISSUED'
"""


# ═══════════════════════════════════════════════════════════
# RFID 태그 쓰기 (웹소켓)
#   핸디 앱이 접속하면 아직 태그를 쓰지 않은 K-LPN 목록을
#   주기적으로 받는다. 두 대가 같은 것을 중복으로 쓰지 않도록
#   완료 회신을 받아 rfid_yn 을 세운다.
# ═══════════════════════════════════════════════════════════

SELECT_KLPN_FOR_RFID = """
SELECT m.lpn_code   AS k_lpn_code,
       k.SEQ        AS kit_seq,
       k.KIT_NO,
       k.MODEL,
       k.ENGINE_NO,
       k.ENGINE_SEQ_NO,
       k.PROC_CODE,
       k.STATION_NO,
       k.STATION_NAME,
       k.WORK_CENTER_NM,
       m.created_date
  FROM lpn_master m
  JOIN kit_table  k ON k.SEQ = m.kit_seq
 WHERE m.lpn_type = 'K'
   AND m.process_status = 'CREATED'
   AND m.lifecycle_status = 'ACTIVE'
   AND k.STATION_NO IS NOT NULL
   AND ISNULL(m.rfid_yn, 0) = 0
 ORDER BY m.created_date
"""

# 태그 쓰기 완료
#   파라미터 : worker_id, lpn_code
MARK_RFID_DONE = """
UPDATE lpn_master
   SET rfid_yn = 1, rfid_date = sysdatetime(), updated_date = sysdatetime()
 WHERE lpn_code = ? AND lpn_type = 'K' AND ISNULL(rfid_yn, 0) = 0
"""