SELECT_ALL_GROUP_KIT = """
SELECT p.seq,
       p.kit_seq,
       p.pick_no,
       p.order_no,
       p.model,
       k.kit_no,
       k.engine_seq_no,
       k.engine_no,
       k.proc_code,
       k.work_center_nm,
       k.delivery_seq,
       k.status   AS kit_status,
       k.hold_yn,
       k.w_lpn_seq,
       k.d_lpn_seq,
       w.lpn_code       AS w_lpn_code,
       w.process_status AS w_lpn_status,
       wl.location_code AS w_location,
       d.lpn_code       AS d_lpn_code,
       d.process_status AS d_lpn_status,
       dl.location_code AS d_location,
       p.item_code,
       p.item_name,
       p.req_qty,
       p.picked_qty,
       p.uom,
       p.lpn_type,
       p.src_type,
       p.status,
       p.plan_date,
       m.proc_order
  FROM PICK_TABLE p
  JOIN KIT_TABLE  k ON k.seq = p.kit_seq
  LEFT JOIN proc_master m ON m.model = p.model
                         AND m.proc_code = p.vornr
                         AND m.use_yn = 1
  LEFT JOIN lpn_master w  ON w.seq = k.w_lpn_seq
  LEFT JOIN location_master wl ON wl.seq = w.location_seq
  LEFT JOIN lpn_master d  ON d.seq = k.d_lpn_seq
  LEFT JOIN location_master dl ON dl.seq = d.location_seq
 WHERE p.status IN ('ISSUED','PICKED')
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
   AND p.plan_date >= CONVERT(char(10), GETDATE(), 23)
 ORDER BY p.plan_date,
          ISNULL(m.proc_order, 9999),
          k.engine_seq_no,
          CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          p.item_code
"""
# ── 단일 조회 (태블릿 피킹 화면) ────────────────────────────
#   1행 = 1스캔 단위. 한 자재가 여러 팔레트에 걸리면 행이 나뉜다.
#   예) A볼트 24개 → A-01-02 에서 9개 / A-03-03 에서 15개 → 2행
#   파라미터 : kit_seq


# 피킹리스트 1장 — 지시번호 기준
#   파라미터 : pick_no
SELECT_BY_PICK_NO = """
SELECT p.seq,
       p.pick_no,
       p.src_type,
       p.kit_seq,
       p.order_no,
       k.kit_no,
       k.engine_seq_no,
       k.engine_no,
       k.proc_code,
       k.work_center_nm,
       k.delivery_seq,
       k.status   AS kit_status,
       k.hold_yn,
       k.w_lpn_seq,
       k.d_lpn_seq,
       w.lpn_code       AS w_lpn_code,
       w.process_status AS w_lpn_status,
       wl.location_code AS w_location,
       d.lpn_code       AS d_lpn_code,
       d.process_status AS d_lpn_status,
       dl.location_code AS d_location,
       p.item_code,
       p.item_name,
       p.req_qty,
       p.picked_qty,
       p.uom,
       p.lpn_type,
       p.status,
       i.size_type,
       t.seq      AS txn_seq,
       t.qty      AS plan_qty,
       t.status   AS txn_status,
       m.lpn_code AS r_lpn_code,
       l.location_code
  FROM PICK_TABLE p
  JOIN KIT_TABLE  k ON k.seq = p.kit_seq
  LEFT JOIN item_master i ON i.seq = p.item_seq
  LEFT JOIN lpn_master w  ON w.seq = k.w_lpn_seq
  LEFT JOIN location_master wl ON wl.seq = w.location_seq
  LEFT JOIN lpn_master d  ON d.seq = k.d_lpn_seq
  LEFT JOIN location_master dl ON dl.seq = d.location_seq
  LEFT JOIN lpn_txn t ON t.PICK_SEQ = p.seq
                     AND t.txn_type = 'PK'
                     AND t.status IN ('PLAN','DONE')
  LEFT JOIN lpn_master      m ON m.seq = t.lpn_master_seq
  LEFT JOIN location_master l ON l.seq = m.location_seq
 WHERE p.pick_no = ?
   AND p.status IN ('ISSUED','PICKED')
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          l.location_code,
          p.item_code
"""

# ── W/D-LPN 선발행 ──────────────────────────────────────────
INSERT_LPN_MASTER = """
INSERT INTO lpn_master
    (lpn_code, lpn_type, process_status, lifecycle_status,
     print_yn, split_yn, kit_seq, order_no, engine_no, proc_code, engine_seq_no)
OUTPUT INSERTED.seq
VALUES (?, ?, 'CREATED', 'ACTIVE', 0, 0, ?, ?, ?, ?, ?);
"""

# 선발행 시점에는 실물 미적재이므로 current_qty = 0
#   UQ_LPN_DETAIL(lpn_master_seq, item_seq) 때문에 동일 품번은 합산 필수
INSERT_LPN_DETAIL_FROM_PICK = """
INSERT INTO lpn_detail (lpn_master_seq, item_seq, init_qty, current_qty)
SELECT ?, p.ITEM_SEQ, SUM(p.REQ_QTY), 0
  FROM pick_table p
 WHERE p.KIT_SEQ = ? AND p.LPN_TYPE = ?
   AND p.STATUS = 'ISSUED'
   AND p.LIFECYCLE_STATUS = 'ACTIVE'
   AND p.ITEM_SEQ IS NOT NULL
 GROUP BY p.ITEM_SEQ;
"""

UPDATE_KIT_W_LPN_SEQ = """
UPDATE kit_table
   SET W_LPN_SEQ = ?, UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND W_LPN_SEQ IS NULL;
"""

UPDATE_KIT_D_LPN_SEQ = """
UPDATE kit_table
   SET D_LPN_SEQ = ?, UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND D_LPN_SEQ IS NULL;
"""

UPDATE_KIT_LPN = {
    "W": UPDATE_KIT_W_LPN_SEQ,
    "D": UPDATE_KIT_D_LPN_SEQ,
}

COUNT_PICK_BY_TYPE = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ? AND LPN_TYPE = ?
   AND STATUS = 'ISSUED' AND LIFECYCLE_STATUS = 'ACTIVE';
"""

SELECT_KIT_HEAD = """
SELECT ORDER_NO, ENGINE_NO, PROC_CODE, ENGINE_SEQ_NO, W_LPN_SEQ, D_LPN_SEQ
  FROM kit_table WHERE SEQ = ? AND LIFECYCLE_STATUS = 'ACTIVE';
"""

COUNT_PICK_NO_ITEM = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ? AND ITEM_SEQ IS NULL
   AND STATUS = 'ISSUED' AND LIFECYCLE_STATUS = 'ACTIVE';
"""


# ═══════════════════════════════════════════════════════════
# 하향 스캔 — R-LPN → W/D-LPN
#   확정 시 만들어둔 lpn_txn PLAN 을 DONE 으로 확정하며 실제 차감.
# ═══════════════════════════════════════════════════════════

#   파라미터 : pick_seq
SELECT_PICK_LINE = """
SELECT p.SEQ, p.KIT_SEQ, p.ITEM_SEQ, p.ITEM_CODE, p.ITEM_NAME,
       p.REQ_QTY, p.PICKED_QTY, p.LPN_TYPE, p.STATUS,
       k.W_LPN_SEQ, k.D_LPN_SEQ, k.HOLD_YN
  FROM pick_table p
  JOIN kit_table  k ON k.SEQ = p.KIT_SEQ
 WHERE p.SEQ = ?
   AND p.LIFECYCLE_STATUS = 'ACTIVE'
   AND k.LIFECYCLE_STATUS = 'ACTIVE'
"""

#   파라미터 : lpn_code
SELECT_R_LPN_BY_CODE = """
SELECT seq, lpn_type, process_status, location_seq
  FROM lpn_master
 WHERE lpn_code = ? AND lifecycle_status = 'ACTIVE'
"""

# 이 지시로 이 팔레트에 걸린 예약. 없으면 오피킹.
#   파라미터 : pick_seq, lpn_master_seq
SELECT_PLAN_TXN = """
SELECT t.seq, t.qty, t.item_seq, d.seq AS detail_seq
  FROM lpn_txn t
  JOIN lpn_detail d ON d.lpn_master_seq = t.lpn_master_seq
                   AND d.item_seq       = t.item_seq
 WHERE t.PICK_SEQ = ? AND t.lpn_master_seq = ?
   AND t.txn_type = 'PK' AND t.status = 'PLAN'
"""

# 차감 직전 실물 행 잠금
LOCK_DETAIL = """
SELECT current_qty FROM lpn_detail WITH (UPDLOCK, HOLDLOCK) WHERE seq = ?
"""

# PLAN → DONE
#   파라미터 : to_lpn_seq, to_detail_seq, from_location_seq,
#              device_id, worker_id, txn_seq
DONE_TXN = """
UPDATE lpn_txn
   SET status            = 'DONE',
       to_lpn_seq        = ?,
       to_detail_seq     = ?,
       from_location_seq = ?,
       device_id         = ?,
       worker_id         = ?,
       txn_date          = sysdatetime()
 WHERE seq = ? AND status = 'PLAN'
"""

# R-LPN 차감   파라미터 : qty, detail_seq
MINUS_QTY = """
UPDATE lpn_detail
   SET current_qty = current_qty - ?, updated_date = sysdatetime()
 WHERE seq = ?
"""

# W/D-LPN 적재   파라미터 : qty, lpn_master_seq, item_seq
PLUS_QTY = """
UPDATE lpn_detail
   SET current_qty = current_qty + ?, updated_date = sysdatetime()
 OUTPUT INSERTED.seq
 WHERE lpn_master_seq = ? AND item_seq = ?
"""

# 잔량 처리 — 남으면 split_yn=1(차기 최우선), 0이면 CONSUMED
#   파라미터 : lpn_master_seq
UPDATE_R_LPN_AFTER = """
UPDATE m
   SET split_yn       = CASE WHEN d.total > 0 THEN 1 ELSE m.split_yn END,
       process_status = CASE WHEN d.total = 0 THEN 'CONSUMED'
                             ELSE m.process_status END,
       updated_date   = sysdatetime()
  FROM lpn_master m
  CROSS APPLY (SELECT SUM(current_qty) AS total
                 FROM lpn_detail WHERE lpn_master_seq = m.seq) d
 WHERE m.seq = ?
"""

# 실적 누적. 지시수량 도달 시 PICKED
#   파라미터 : qty, qty, pick_seq
UPDATE_PICKED_QTY = """
UPDATE pick_table
   SET PICKED_QTY = PICKED_QTY + ?,
       STATUS     = CASE WHEN PICKED_QTY + ? >= REQ_QTY THEN 'PICKED'
                         ELSE STATUS END,
       UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND STATUS = 'ISSUED'
"""

# ═══════════════════════════════════════════════════════════
# W/D-LPN 바인딩 — 위치 + LPN 스캔
#   W : WASH_COMP  (세척 완료 버퍼 적치)
#   D : PICK_COMP  (비세척 버퍼 적치, 위치만 등록)
#   임의 빈 셀에 적치하는 동적 매핑이라 위치는 스캔 시점에 정해진다.
# ═══════════════════════════════════════════════════════════

#   파라미터 : lpn_code
SELECT_LPN_BY_CODE = """
SELECT m.seq, m.lpn_type, m.process_status, m.kit_seq, m.location_seq,
       k.HOLD_YN
  FROM lpn_master m
  LEFT JOIN kit_table k ON k.SEQ = m.kit_seq
 WHERE m.lpn_code = ? AND m.lifecycle_status = 'ACTIVE'
"""

# 지시 자재가 전부 담겼는가. 미완료 건수 반환.
#   파라미터 : kit_seq, lpn_type
COUNT_PICK_NOT_DONE = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ? AND LPN_TYPE = ?
   AND STATUS <> 'PICKED'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 위치 유효성. 점유 검사는 하지 않는다(한 셀 복수 LPN 허용).
#   파라미터 : location_code
CHECK_LOCATION = """
SELECT l.seq, z.zone_code
  FROM location_master l
  JOIN rack_master r ON r.seq = l.rack_seq
  JOIN zone_master z ON z.seq = r.zone_seq
 WHERE l.location_code = ? AND l.enable_yn = 1 AND r.enable_yn = 1
"""

# 위치 바인딩
#   파라미터 : location_seq, to_status, lpn_master_seq, from_status
BIND_LOCATION = """
UPDATE lpn_master
   SET location_seq   = ?,
       process_status = ?,
       updated_date   = sysdatetime()
 WHERE seq = ? AND process_status = ?
"""

# 이동 이력. 담긴 자재 전 행을 돈다.
#   파라미터 : from_location_seq, to_location_seq, device_id, worker_id,
#              lpn_master_seq
INSERT_TXN_MOVE = """
INSERT INTO lpn_txn
      (txn_type, status, lpn_master_seq, item_seq, qty,
       from_location_seq, to_location_seq, device_id, worker_id)
SELECT 'MV', 'DONE', d.lpn_master_seq, d.item_seq, d.current_qty,
       ?, ?, ?, ?
  FROM lpn_detail d
 WHERE d.lpn_master_seq = ? AND d.current_qty > 0
"""


MOVE_TO_WASH_WAIT = """
UPDATE lpn_master
   SET process_status = 'WASH_WAIT',
       location_seq   = NULL,
       updated_date   = sysdatetime()
 WHERE seq = ? AND process_status = 'PICK_COMP'
"""

# 하향 완료 시 W/D-LPN 을 PICK_COMP 로 올린다.
#   파라미터 : lpn_master_seq
SET_PICK_COMP = """
UPDATE lpn_master
   SET process_status = 'PICK_COMP', updated_date = sysdatetime()
 WHERE seq = ? AND process_status IN ('CREATED','PRINTED')
   AND NOT EXISTS (
       SELECT 1 FROM pick_table
        WHERE KIT_SEQ = ? AND LPN_TYPE = ?
          AND STATUS <> 'PICKED'
          AND LIFECYCLE_STATUS = 'ACTIVE'
   )
"""

# LPN 코드로 재발행 대상 조회
#   파라미터 : lpn_code
SELECT_REISSUE_TARGET_BY_CODE = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status,
       m.kit_seq, m.order_no, m.engine_no, m.proc_code,
       k.WORK_CENTER_NM, k.STATUS AS kit_status,
       CASE WHEN m.process_status IN ('CREATED','PRINTED') THEN 1 ELSE 0 END AS can_reissue
  FROM lpn_master m
  LEFT JOIN kit_table k ON k.SEQ = m.kit_seq
 WHERE m.lpn_code = ? AND m.lifecycle_status = 'ACTIVE'
"""

#   파라미터 : lpn_seq
SELECT_REISSUE_TARGET_BY_SEQ = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status,
       m.kit_seq, m.order_no, m.engine_no, m.proc_code,
       k.WORK_CENTER_NM, k.STATUS AS kit_status,
       CASE WHEN m.process_status IN ('CREATED','PRINTED') THEN 1 ELSE 0 END AS can_reissue
  FROM lpn_master m
  LEFT JOIN kit_table k ON k.SEQ = m.kit_seq
 WHERE m.seq = ? AND m.lifecycle_status = 'ACTIVE'
"""

REPRINT_LPN = """
UPDATE lpn_master
   SET reprint_cnt  = reprint_cnt + 1,
       print_yn     = 1,
       updated_date = sysdatetime()
 OUTPUT INSERTED.lpn_code, INSERTED.reprint_cnt
 WHERE seq = ? AND process_status IN ('CREATED','PRINTED')
"""


# 라벨 발행 시 피킹 착수로 전이
#   파라미터 : kit_seq
START_PICKING = """
UPDATE kit_table
   SET STATUS = 'PICKING', UPDATED_DATE = sysdatetime()
 WHERE SEQ = ? AND STATUS = 'WAIT'
"""


# 피킹리스트 1장 — 키팅 기준 (긴급 보충 포함)
#   파라미터 : kit_seq
SELECT_BY_SEQ_GROUP_KIT = """
SELECT p.seq,
       p.kit_seq,
       p.pick_no,
       p.order_no,
       p.model,
       k.kit_no,
       k.engine_seq_no,
       k.engine_no,
       k.proc_code,
       k.work_center_nm,
       k.delivery_seq,
       k.status   AS kit_status,
       k.hold_yn,
       k.w_lpn_seq,
       k.d_lpn_seq,
       p.item_code,
       p.item_name,
       p.req_qty,
       p.picked_qty,
       p.uom,
       p.lpn_type,
       p.status,
       t.seq      AS txn_seq,
       t.qty      AS plan_qty,
       t.status   AS txn_status,
       m.lpn_code AS r_lpn_code,
       l.location_code
  FROM PICK_TABLE p
  JOIN KIT_TABLE  k ON k.seq = p.kit_seq
  LEFT JOIN lpn_txn t ON t.PICK_SEQ = p.seq
                     AND t.txn_type = 'PK'
                     AND t.status IN ('PLAN','DONE')
  LEFT JOIN lpn_master      m ON m.seq = t.lpn_master_seq
  LEFT JOIN location_master l ON l.seq = m.location_seq
 WHERE p.kit_seq = ?
   AND p.status IN ('ISSUED','PICKED')
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          l.location_code,
          p.item_code
"""



# 긴급 보충이 붙어 있으면 확정 취소 불가.
# 긴급분은 확정 단계를 건너뛴 지시라 WAIT 으로 되돌릴 수 없다.
#   파라미터 : kit_seq
COUNT_EMERGENCY_ATTACHED = """
SELECT COUNT(*) FROM pick_table
 WHERE KIT_SEQ = ? AND SRC_TYPE = 'URGENT'
   AND LIFECYCLE_STATUS = 'ACTIVE'
"""