SELECT_BASE = """
SELECT
    ISNULL(tm.seq,       m.seq)       AS lpn_master_seq,
    ISNULL(tm.lpn_code,  m.lpn_code)  AS lpn_code,
    ISNULL(tm.lpn_type,  m.lpn_type)  AS lpn_type,
    ISNULL(tm.process_status, m.process_status) AS process_status,

    t.seq        AS txn_seq,
    t.txn_type,
    t.status,
    t.qty,
    t.txn_date,
    t.device_id,
    t.worker_id,

    i.item_code,
    i.item_name,
    i.uom,
    i.washing_yn,

    dd.init_qty     AS lpn_init_qty,
    dd.current_qty  AS lpn_current_qty,
    ISNULL(al.plan_qty, 0)                  AS lpn_allocated_qty,
    dd.current_qty - ISNULL(al.plan_qty, 0) AS lpn_available_qty,

    p.PICK_NO,
    k.KIT_NO,

    CASE WHEN t.to_lpn_seq IS NULL THEN NULL ELSE m.lpn_code END AS pre_lpn_code,
    CASE WHEN t.to_lpn_seq IS NULL THEN NULL ELSE m.lpn_type END AS pre_lpn_type,

    fl.location_code AS from_location_code,
    tl.location_code AS to_location_code,
    ISNULL(tz.zone_name, fz.zone_name) AS zone_name,

    ISNULL(tm.order_no,      m.order_no)      AS order_no,
    ISNULL(tm.engine_no,     m.engine_no)     AS engine_no,
    ISNULL(tm.proc_code,     m.proc_code)     AS proc_code,
    ISNULL(tm.engine_seq_no, m.engine_seq_no) AS engine_seq_no
FROM lpn_txn t
JOIN lpn_master m        ON m.seq = t.lpn_master_seq
LEFT JOIN lpn_master tm  ON tm.seq = t.to_lpn_seq
LEFT JOIN item_master i  ON i.seq = t.item_seq
LEFT JOIN pick_table p   ON p.SEQ = t.PICK_SEQ
LEFT JOIN kit_table  k   ON k.SEQ = p.KIT_SEQ
LEFT JOIN lpn_detail dd  ON dd.lpn_master_seq = ISNULL(tm.seq, m.seq)
                        AND dd.item_seq       = t.item_seq
LEFT JOIN location_master fl ON fl.seq = t.from_location_seq
LEFT JOIN rack_master     fr ON fr.seq = fl.rack_seq
LEFT JOIN zone_master     fz ON fz.seq = fr.zone_seq
LEFT JOIN location_master tl ON tl.seq = t.to_location_seq
LEFT JOIN rack_master     tr ON tr.seq = tl.rack_seq
LEFT JOIN zone_master     tz ON tz.seq = tr.zone_seq
OUTER APPLY (
    SELECT SUM(x.qty) AS plan_qty
      FROM lpn_txn x
     WHERE x.lpn_master_seq = ISNULL(tm.seq, m.seq)
       AND x.item_seq       = t.item_seq
       AND x.txn_type = 'PK'
       AND x.status   = 'PLAN'
) al
WHERE t.status = 'DONE'
  AND t.txn_date >= ?
  AND t.txn_date <  DATEADD(DAY, 1, ?)
"""

ORDER_BY = """
ORDER BY t.txn_date DESC, ISNULL(tm.seq, m.seq), t.seq
"""


# 거래 유형   IN / PK / MV / MG / SC
F_TXN_TYPE = "  AND t.txn_type = ?\n"

# 대표 LPN 유형   R / W / D / K
F_LPN_TYPE = "  AND ISNULL(tm.lpn_type, m.lpn_type) = ?\n"

# 구역   출발·도착 어느 쪽이든 해당 구역이면 잡는다
F_ZONE = "  AND ISNULL(tz.zone_code, fz.zone_code) = ?\n"

# 지시번호   PIK / KIT 어느 쪽으로 검색해도 잡히게
F_DOC_NO = """  AND (p.PICK_NO LIKE ? OR k.KIT_NO LIKE ?)
"""

# 위치   앞부분만 넣으면 랙 단위로 잡힌다 (예: MAIN-R01)
F_LOCATION = """  AND (fl.location_code LIKE ? OR tl.location_code LIKE ?)
"""

# 통합 검색   LPN / 위치 / 자재 / 호기
F_KEYWORD = """  AND (m.lpn_code       LIKE ?
    OR tm.lpn_code      LIKE ?
    OR fl.location_code LIKE ?
    OR tl.location_code LIKE ?
    OR i.item_code      LIKE ?
    OR i.item_name      LIKE ?
    OR m.engine_no      LIKE ?)
"""


# ── 셀렉트박스 소스 ─────────────────────────────────────────
SELECT_LPN_TYPES = """
SELECT code, code_name, sort_order
  FROM common_code
 WHERE group_code = 'LPN_TYPE' AND use_yn = 1
 ORDER BY sort_order
"""

SELECT_ZONES = """
SELECT zone_code, zone_name, zone_type
  FROM zone_master
 ORDER BY zone_code
"""


# 저재고 조회 — R-LPN 단위. 팔레트별 잔량이 임계치 미만인 건.
#   ※ 자재 합계가 아니라 팔레트 하나하나를 본다.
#     같은 자재가 여러 팔레트에 흩어져 있어도 각각 판정한다.
#   파라미터 : threshold
SELECT_LOW_STOCK = """
SELECT V.lpn_master_seq, V.lpn_code, V.detail_seq,
       i.seq AS item_seq, i.item_code, i.item_name, i.uom,
       i.washing_yn, i.size_type,
       V.current_qty, V.allocated_qty, V.available_qty,
       V.split_yn, V.receipt_date,
       l.location_code, z.zone_name
  FROM V_LPN_ALLOCATABLE V
  JOIN item_master i ON i.seq = V.item_seq
  LEFT JOIN location_master l ON l.seq = V.location_seq
  LEFT JOIN rack_master     r ON r.seq = l.rack_seq
  LEFT JOIN zone_master     z ON z.seq = r.zone_seq
 WHERE V.lpn_type = 'R'
   AND V.process_status = 'AVAILABLE'
   AND V.available_qty < ?
 ORDER BY V.available_qty, i.item_code, V.lpn_code
"""

# ── 피킹리스트 이력 ─────────────────────────────────────────
#   1행 = [오더 + 공정] 단위 지시. 자재 진척을 집계로 보여준다.
#   파라미터 : date_from, date_to
SELECT_PICK_HISTORY = """
SELECT p.PICK_NO,
       p.ORDER_NO,
       p.VORNR              AS PROC_CODE,
       MAX(m.proc_name)     AS PROC_NAME,
       MAX(p.ENGINE_NO)     AS ENGINE_NO,
       MAX(p.ENGINE_SEQ_NO) AS ENGINE_SEQ_NO,
       MAX(p.PLAN_DATE)     AS PLAN_DATE,
       MAX(k.SEQ)           AS KIT_SEQ,
       MAX(k.KIT_NO)        AS KIT_NO,
       MAX(k.STATUS)        AS KIT_STATUS,
       COUNT(*)                                            AS item_cnt,
       SUM(p.REQ_QTY)                                      AS req_qty,
       SUM(p.PICKED_QTY)                                   AS picked_qty,
       SUM(CASE WHEN p.STATUS = 'PICKED' THEN 1 ELSE 0 END) AS picked_cnt,
       SUM(CASE WHEN p.STATUS = 'SHORT'  THEN 1 ELSE 0 END) AS short_cnt,
       SUM(CASE WHEN p.LPN_TYPE = 'W' THEN 1 ELSE 0 END)   AS wash_cnt,
       SUM(CASE WHEN p.LPN_TYPE = 'D' THEN 1 ELSE 0 END)   AS dry_cnt,
       MIN(p.CREATED_DATE)  AS created_date,
       MAX(p.UPDATED_DATE)  AS updated_date,
       MAX(p.LIFECYCLE_STATUS) AS lifecycle_status
  FROM pick_table p
  LEFT JOIN kit_table k
         ON k.SEQ = p.KIT_SEQ
  LEFT JOIN proc_master m
         ON m.proc_code = p.VORNR AND m.use_yn = 1
 WHERE p.CREATED_DATE >= ?
   AND p.CREATED_DATE <  DATEADD(DAY, 1, ?)
 GROUP BY p.PICK_NO, p.ORDER_NO, p.VORNR
HAVING SUM(CASE WHEN p.STATUS <> 'PICKED' THEN 1 ELSE 0 END) = 0
"""

PICK_ORDER_BY = """
 ORDER BY MAX(p.PLAN_DATE) DESC, MAX(p.ENGINE_SEQ_NO), p.VORNR
"""

F_PICK_STATUS = "  AND p.STATUS = ?\n"
F_PICK_NO     = "  AND p.PICK_NO LIKE ?\n"
F_PICK_KEYWORD = """  AND (p.PICK_NO    LIKE ?
    OR p.ORDER_NO   LIKE ?
    OR p.ENGINE_NO  LIKE ?
    OR p.ITEM_CODE  LIKE ?
    OR p.ITEM_NAME  LIKE ?)
"""

# 피킹리스트 1건 상세 — 헤더 + 자재
#   파라미터 : pick_no
SELECT_PICK_HISTORY_ITEMS = """
SELECT p.SEQ, p.PICK_NO, p.SRC_TYPE, p.SRC_PICK_SEQ, p.REMARK,
       p.ORDER_NO, p.VORNR, p.ENGINE_NO, p.ENGINE_SEQ_NO, p.PLAN_DATE,
       p.ITEM_CODE, p.ITEM_NAME, p.ITEM_SEQ, p.UOM,
       p.REQ_QTY, p.PICKED_QTY, p.LPN_TYPE, p.STATUS,
       p.LIFECYCLE_STATUS, p.CREATED_DATE, p.UPDATED_DATE,
       k.SEQ AS KIT_SEQ, k.KIT_NO, k.STATUS AS KIT_STATUS,
       k.WORK_CENTER_NM, k.DELIVERY_SEQ,
       w.lpn_code       AS w_lpn_code,
       w.process_status AS w_lpn_status,
       wl.location_code AS w_location,
       d.lpn_code       AS d_lpn_code,
       d.process_status AS d_lpn_status,
       dl.location_code AS d_location,
       m.proc_name
  FROM pick_table p
  LEFT JOIN kit_table k ON k.SEQ = p.KIT_SEQ
  LEFT JOIN lpn_master w  ON w.seq = k.W_LPN_SEQ
  LEFT JOIN location_master wl ON wl.seq = w.location_seq
  LEFT JOIN lpn_master d  ON d.seq = k.D_LPN_SEQ
  LEFT JOIN location_master dl ON dl.seq = d.location_seq
  LEFT JOIN proc_master m ON m.proc_code = p.VORNR AND m.use_yn = 1
 WHERE p.PICK_NO = ?
 ORDER BY CASE WHEN p.LPN_TYPE = 'W' THEN 0 ELSE 1 END, p.ITEM_CODE
"""

# ── 키팅리스트 이력 ─────────────────────────────────────────
#   파라미터 : date_from, date_to
SELECT_KIT_HISTORY = """
SELECT k.SEQ AS kit_seq, k.KIT_NO, k.ORDER_NO, k.PROC_CODE,
       k.WORK_CENTER_NM, k.ENGINE_NO, k.ENGINE_SEQ_NO,
       k.PLAN_DATE, k.DELIVERY_SEQ, k.STATUS, k.HOLD_YN,
       k.LIFECYCLE_STATUS, k.CREATED_DATE, k.UPDATED_DATE, k.DEPARTED_DATE,
       w.lpn_code AS w_lpn_code, w.process_status AS w_status,
       d.lpn_code AS d_lpn_code, d.process_status AS d_status,
       kl.lpn_code AS k_lpn_code,
       p.item_cnt, p.req_qty, p.picked_qty, p.picked_cnt,
       v.pass_cnt, v.fail_cnt
  FROM kit_table k
  LEFT JOIN lpn_master w  ON w.seq  = k.W_LPN_SEQ
  LEFT JOIN lpn_master d  ON d.seq  = k.D_LPN_SEQ
  LEFT JOIN lpn_master kl ON kl.seq = k.K_LPN_SEQ
  OUTER APPLY (
      SELECT COUNT(*) AS item_cnt,
             SUM(REQ_QTY) AS req_qty,
             SUM(PICKED_QTY) AS picked_qty,
             SUM(CASE WHEN STATUS = 'PICKED' THEN 1 ELSE 0 END) AS picked_cnt
        FROM pick_table
       WHERE KIT_SEQ = k.SEQ AND LIFECYCLE_STATUS = 'ACTIVE'
  ) p
  OUTER APPLY (
      SELECT SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END) AS pass_cnt,
             SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) AS fail_cnt
        FROM kit_verify_log
       WHERE kit_seq = k.SEQ
  ) v
 WHERE k.CREATED_DATE >= ?
   AND k.CREATED_DATE <  DATEADD(DAY, 1, ?)
   AND k.STATUS = 'KITTED'
"""

KIT_ORDER_BY = """
 ORDER BY k.PLAN_DATE DESC, k.ENGINE_SEQ_NO, k.DELIVERY_SEQ
"""

F_KIT_STATUS = "  AND k.STATUS = ?\n"
F_KIT_NO     = "  AND k.KIT_NO LIKE ?\n"
F_KIT_KEYWORD = """  AND (k.KIT_NO     LIKE ?
    OR k.ORDER_NO   LIKE ?
    OR k.ENGINE_NO  LIKE ?
    OR k.PROC_CODE  LIKE ?)
"""


# 키팅리스트 1건 상세 — 헤더 + 자재 + LPN + 검증 이력
#   파라미터 : kit_no
SELECT_KIT_HISTORY_ITEMS = """
SELECT k.SEQ AS KIT_SEQ, k.KIT_NO, k.ORDER_NO, k.PROC_CODE,
       k.WORK_CENTER_NM, k.ENGINE_NO, k.ENGINE_SEQ_NO,
       k.PLAN_DATE, k.DELIVERY_SEQ, k.STATUS AS KIT_STATUS,
       k.HOLD_YN, k.LIFECYCLE_STATUS,
       k.CREATED_DATE, k.UPDATED_DATE, k.DEPARTED_DATE,
       w.lpn_code       AS w_lpn_code,
       w.process_status AS w_lpn_status,
       wl.location_code AS w_location,
       d.lpn_code       AS d_lpn_code,
       d.process_status AS d_lpn_status,
       dl.location_code AS d_location,
       kl.lpn_code      AS k_lpn_code,
       kl.process_status AS k_lpn_status,
       p.SEQ AS pick_seq, p.PICK_NO, p.SRC_TYPE,
       p.ITEM_CODE, p.ITEM_NAME, p.UOM,
       p.REQ_QTY, p.PICKED_QTY, p.LPN_TYPE, p.STATUS AS pick_status
  FROM kit_table k
  LEFT JOIN lpn_master w  ON w.seq  = k.W_LPN_SEQ
  LEFT JOIN location_master wl ON wl.seq = w.location_seq
  LEFT JOIN lpn_master d  ON d.seq  = k.D_LPN_SEQ
  LEFT JOIN location_master dl ON dl.seq = d.location_seq
  LEFT JOIN lpn_master kl ON kl.seq = k.K_LPN_SEQ
  LEFT JOIN pick_table p  ON p.KIT_SEQ = k.SEQ
                         AND p.LIFECYCLE_STATUS = 'ACTIVE'
 WHERE k.KIT_NO = ?
 ORDER BY CASE WHEN p.LPN_TYPE = 'W' THEN 0 ELSE 1 END, p.ITEM_CODE
"""

# 그 키팅의 3중 검증 이력
#   파라미터 : kit_no
SELECT_KIT_VERIFY_BY_NO = """
SELECT v.seq, v.scan_code, v.verify_seq_yn, v.verify_proc_yn, v.verify_stat_yn,
       v.result, v.fail_reason, v.device_id, v.worker_id, v.verify_date,
       m.lpn_type
  FROM kit_verify_log v
  JOIN kit_table k ON k.SEQ = v.kit_seq
  LEFT JOIN lpn_master m ON m.seq = v.lpn_master_seq
 WHERE k.KIT_NO = ?
 ORDER BY v.verify_date, v.seq
"""


# ── B. LPN 추적 — 한 LPN 의 생애 ────────────────────────────
#   출발이든 도착이든 이 LPN 이 관련된 모든 거래.
#   direction : OUT = 이 LPN 에서 나감 / IN = 이 LPN 으로 들어옴
#   기간 제한 없음. 파라미터 : lpn_code(direction), lpn_code, lpn_code
SELECT_BY_LPN = """
SELECT
    t.seq        AS txn_seq,
    t.txn_type,
    t.status,
    t.qty,
    t.txn_date,
    t.device_id,
    t.worker_id,

    m.lpn_code        AS from_lpn_code,
    m.lpn_type        AS from_lpn_type,
    tm.lpn_code       AS to_lpn_code,
    tm.lpn_type       AS to_lpn_type,

    i.item_code, i.item_name, i.uom,
    fl.location_code  AS from_location_code,
    tl.location_code  AS to_location_code,
    CASE WHEN m.lpn_code = ? THEN 'OUT' ELSE 'IN' END AS direction
FROM lpn_txn t
JOIN lpn_master m        ON m.seq = t.lpn_master_seq
LEFT JOIN lpn_master tm  ON tm.seq = t.to_lpn_seq
LEFT JOIN item_master i  ON i.seq = t.item_seq
LEFT JOIN location_master fl ON fl.seq = t.from_location_seq
LEFT JOIN location_master tl ON tl.seq = t.to_location_seq
WHERE m.lpn_code = ? OR tm.lpn_code = ?
ORDER BY t.txn_date, t.seq
"""

# ── LPN 상세 ────────────────────────────────────────────────
#   items 는 한 단계만 보여준다.
#     K-LPN   → W/D-LPN 목록
#     W/D-LPN → R-LPN 목록
#     R-LPN   → 자재 목록
#   더 파고들려면 자식을 클릭해 그 LPN 을 다시 조회한다.

#   파라미터 : lpn_code
SELECT_LPN_HEAD = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status, m.lifecycle_status,
       m.print_yn, m.reprint_cnt, m.split_yn,
       m.receipt_date, m.created_date, m.updated_date,
       m.kit_seq, m.order_no, m.engine_no, m.proc_code, m.engine_seq_no,
       l.location_code, z.zone_name,
       k.KIT_NO, k.STATUS AS kit_status, k.WORK_CENTER_NM
  FROM lpn_master m
  LEFT JOIN location_master l ON l.seq = m.location_seq
  LEFT JOIN rack_master     r ON r.seq = l.rack_seq
  LEFT JOIN zone_master     z ON z.seq = r.zone_seq
  LEFT JOIN kit_table       k ON k.SEQ = m.kit_seq
 WHERE m.lpn_code = ?
"""

# 하위 LPN — 이 용기로 자재가 들어온 출처
#   파라미터 : lpn_code
SELECT_LPN_SOURCES = """
SELECT DISTINCT
       m.seq, m.lpn_code, m.lpn_type, m.process_status, m.lifecycle_status,
       l.location_code
  FROM lpn_txn t
  JOIN lpn_master tm ON tm.seq = t.to_lpn_seq
  JOIN lpn_master m  ON m.seq  = t.lpn_master_seq
  LEFT JOIN location_master l ON l.seq = m.location_seq
 WHERE tm.lpn_code = ? AND t.status = 'DONE'
 ORDER BY m.lpn_code
"""

# 담긴 자재 — R-LPN 전용
#   파라미터 : lpn_code
SELECT_LPN_ITEMS = """
SELECT i.item_code, i.item_name, i.uom, i.washing_yn,
       i.mixed_allow, i.kitting_grp,
       d.init_qty, d.current_qty,
       ISNULL(al.plan_qty, 0)                 AS allocated_qty,
       d.current_qty - ISNULL(al.plan_qty, 0) AS available_qty
  FROM lpn_detail d
  JOIN lpn_master m  ON m.seq = d.lpn_master_seq
  JOIN item_master i ON i.seq = d.item_seq
  OUTER APPLY (
      SELECT SUM(x.qty) AS plan_qty
        FROM lpn_txn x
       WHERE x.lpn_master_seq = d.lpn_master_seq
         AND x.item_seq       = d.item_seq
         AND x.txn_type = 'PK'
         AND x.status   = 'PLAN'
  ) al
 WHERE m.lpn_code = ?
 ORDER BY i.item_code
"""


# 같은 kitting_grp 의 혼적 가능 자재 — 함께 담을 수 있는 후보
#   파라미터 : lpn_code
SELECT_LPN_MIXED_GROUP = """
SELECT DISTINCT
       i.seq, i.item_code, i.item_name, i.uom,
       i.washing_yn, i.kitting_grp
  FROM item_master i
 WHERE i.mixed_allow = 1
   AND i.use_yn = 1
   AND i.kitting_grp IN (
       SELECT gi.kitting_grp
         FROM lpn_detail d
         JOIN lpn_master m  ON m.seq = d.lpn_master_seq
         JOIN item_master gi ON gi.seq = d.item_seq
        WHERE m.lpn_code = ?
          AND gi.mixed_allow = 1
          AND gi.kitting_grp IS NOT NULL
   )
 ORDER BY i.item_code
"""