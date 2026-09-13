# -*- coding: utf-8 -*-
"""src/queries/lpn_query.py — LPN SQL"""

# ── 공통 SELECT (LPN + 자재 + 위치 + 구역 조인) ─────────────
SELECT_BASE = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status, m.lifecycle_status,
       m.print_yn, m.split_yn, m.receipt_date, m.created_date,
       i.seq AS item_seq, i.item_code, i.item_name, i.uom, i.washing_yn,
       d.seq AS detail_seq, d.init_qty, d.current_qty,
       l.location_code, z.zone_code
FROM lpn_master m
JOIN lpn_detail d           ON d.lpn_master_seq = m.seq
JOIN item_master i          ON i.seq = d.item_seq
LEFT JOIN location_master l ON l.seq = m.location_seq
LEFT JOIN rack_master r     ON r.seq = l.rack_seq
LEFT JOIN zone_master z     ON z.seq = r.zone_seq
"""

# ── 조회 ────────────────────────────────────────────────────
SELECT_ACTIVE_LPN = SELECT_BASE + """
WHERE m.lifecycle_status = 'ACTIVE'
ORDER BY m.lpn_code
"""

SELECT_BY_ITEM_CODE = SELECT_BASE + """
WHERE i.item_code = ?
  AND m.lpn_type = 'R'
  AND m.process_status = 'AVAILABLE'
  AND m.lifecycle_status = 'ACTIVE'
  AND d.current_qty > 0
ORDER BY m.receipt_date, m.lpn_code
"""

SELECT_BY_SEQ = SELECT_BASE + """
WHERE m.seq = ?
"""

SELECT_R_LPN = SELECT_BASE + """
WHERE m.lpn_type = 'R'
  AND m.lifecycle_status = 'ACTIVE'
ORDER BY m.lpn_code
"""

SELECT_R_LPN_BY_CODE = SELECT_BASE + """
WHERE m.lpn_type = 'R' AND m.lpn_code = ?
"""

# 자재 조회 — 혼적 판정에 필요한 속성까지
#   파라미터 : item_code
SELECT_ITEM_BY_CODE = """
SELECT seq, item_code, item_name, uom, washing_yn, mixed_allow, kitting_grp
  FROM item_master
 WHERE item_code = ? AND use_yn = 1
"""


# ── 1. 입고 등록 ────────────────────────────────────────────
#   process_status 는 DEFAULT 로 CREATED. 위치·라벨 없음.
INSERT_MASTER = """
INSERT INTO lpn_master (lpn_code, lpn_type, process_status,
                        lifecycle_status, location_seq, print_yn, split_yn)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, 'ACTIVE', NULL, 0, 0)
"""

INSERT_DETAIL = """
INSERT INTO lpn_detail (lpn_master_seq, item_seq, init_qty, current_qty)
VALUES (?, ?, ?, ?)
"""


# ── 2. 라벨 발행 ────────────────────────────────────────────
#   CREATED 인 건만 전환. 중복 발행은 rowcount 0 으로 걸러짐.
UPDATE_PRINTED_BY_SEQ = """
UPDATE lpn_master
   SET process_status = 'PRINTED',
       print_yn       = 1,
       updated_date   = SYSDATETIME()
 WHERE seq = ?
   AND process_status = 'CREATED'
   AND lifecycle_status = 'ACTIVE'
"""

# ── 3. 위치 바인딩 → 가용재고 전환 ──────────────────────────
#   receipt_date 는 FIFO 정렬 기준이므로 실제 적치 시점에 찍는다.
UPDATE_AVAILABLE = """
UPDATE lpn_master
   SET location_seq   = ?,
       process_status = 'AVAILABLE',
       receipt_date   = SYSDATETIME(),
       updated_date   = SYSDATETIME()
 WHERE seq = ?
   AND process_status = 'PRINTED'
   AND lifecycle_status = 'ACTIVE'
"""

# 재고 원장 기록. Multi-SKU 대응으로 lpn_detail 전 행을 돈다.
#   파라미터 : to_location_seq, device_id, worker_id, lpn_master_seq
INSERT_TXN_IN = """
INSERT INTO dbo.lpn_txn
      (txn_type, status, lpn_master_seq, item_seq, qty,
       to_location_seq, device_id, worker_id)
SELECT 'IN', 'DONE', D.lpn_master_seq, D.item_seq, D.current_qty,
       ?, ?, ?
  FROM dbo.lpn_detail D
 WHERE D.lpn_master_seq = ?
"""


# ── 위치 유효성 ─────────────────────────────────────────────
#   한 셀에 복수 LPN 적치 가능하므로 점유 여부는 검사하지 않는다.
CHECK_LOCATION_USABLE = """
SELECT 1
  FROM dbo.location_master L
  JOIN dbo.rack_master R ON R.seq = L.rack_seq
 WHERE L.seq = ? AND L.enable_yn = 1 AND R.enable_yn = 1
"""


# ── 정보 수정 / 취소 ────────────────────────────────────────
UPDATE_DETAIL_QTY = """
UPDATE lpn_detail
   SET init_qty     = ?,
       current_qty  = ?,
       updated_date = SYSDATETIME()
 WHERE seq = ?
"""

UPDATE_LOCATION = """
UPDATE lpn_master
   SET location_seq = ?, updated_date = SYSDATETIME()
 WHERE seq = ? AND lifecycle_status = 'ACTIVE'
"""

# ═══════════════════════════════════════════════════════════
# 팔레트 통합 (MG)
#   소스 LPN 의 자재를 타겟 LPN 으로 합치고 소스를 소멸시킨다.
#   보관 효율을 위한 실물 작업이므로 수량 총합은 변하지 않는다.
#
#   ※ R-LPN 만 대상. W/D-LPN 은 호기·공정에 바인딩되어 있어
#     다른 지시의 용기와 합치면 오조립이 된다.
# ═══════════════════════════════════════════════════════════

# 담긴 자재. 수량 0 인 행은 제외.
#   파라미터 : lpn_master_seq
SELECT_DETAIL_FOR_MERGE = """
SELECT d.seq AS detail_seq, d.item_seq, d.current_qty,
       i.item_code, i.item_name
  FROM lpn_detail d
  JOIN item_master i ON i.seq = d.item_seq
 WHERE d.lpn_master_seq = ? AND d.current_qty > 0
 ORDER BY i.item_code
"""

# 할당(PLAN)이 걸려 있는가. 걸려 있으면 통합 불가.
#   파라미터 : lpn_master_seq
COUNT_LPN_PLAN = """
SELECT COUNT(*) FROM lpn_txn
 WHERE lpn_master_seq = ? AND txn_type = 'PK' AND status = 'PLAN'
"""

# 타겟에 같은 자재가 있으면 합산, 없으면 신규.
#   파라미터 : qty, qty, lpn_master_seq, item_seq
ADD_TARGET_QTY = """
UPDATE lpn_detail
   SET init_qty    = init_qty + ?,
       current_qty = current_qty + ?,
       updated_date = sysdatetime()
 OUTPUT INSERTED.seq
 WHERE lpn_master_seq = ? AND item_seq = ?
"""

#   파라미터 : lpn_master_seq, item_seq, qty, qty
INSERT_TARGET_DETAIL = """
INSERT INTO lpn_detail (lpn_master_seq, item_seq, init_qty, current_qty)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, ?)
"""

# 소스 비우기
#   파라미터 : detail_seq
CLEAR_SOURCE_QTY = """
UPDATE lpn_detail
   SET current_qty = 0, updated_date = sysdatetime()
 WHERE seq = ?
"""

# 소스 소멸. 라벨은 폐기되고 번호는 재사용하지 않는다.
#   파라미터 : lpn_master_seq
INACTIVE_SOURCE_LPN = """
UPDATE lpn_master
   SET process_status   = 'CONSUMED',
       lifecycle_status = 'INACTIVE',
       location_seq     = NULL,
       updated_date     = sysdatetime()
 WHERE seq = ?
"""

# 통합 후 타겟은 헐린 팔레트로 표시 — 차기 피킹 최우선
#   파라미터 : lpn_master_seq
SET_TARGET_SPLIT = """
UPDATE lpn_master
   SET split_yn = 1, updated_date = sysdatetime()
 WHERE seq = ?
"""

# 통합 이력
#   파라미터 : target_seq, target_detail_seq, item_seq, qty,
#              from_location_seq, to_location_seq,
#              device_id, worker_id, source_seq
INSERT_TXN_MERGE_PALLET = """
INSERT INTO lpn_txn
      (txn_type, status, lpn_master_seq, to_lpn_seq, to_detail_seq,
       item_seq, qty, from_location_seq, to_location_seq,
       device_id, worker_id)
VALUES ('MG', 'DONE', ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


SELECT_LPN_FOR_MERGE_BY_CODE = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status, m.lifecycle_status,
       m.location_seq, m.split_yn, m.kit_seq,
       l.location_code
  FROM lpn_master m
  LEFT JOIN location_master l ON l.seq = m.location_seq
 WHERE m.lpn_code = ?
"""

# 통합 전 미리보기 — 화면에서 확인용
#   파라미터 : lpn_code
SELECT_MERGE_PREVIEW = """
SELECT m.seq, m.lpn_code, m.lpn_type, m.process_status,
       l.location_code, m.receipt_date, m.split_yn,
       i.item_code, i.item_name, d.current_qty, d.init_qty, i.uom
  FROM lpn_master m
  LEFT JOIN location_master l ON l.seq = m.location_seq
  LEFT JOIN lpn_detail d ON d.lpn_master_seq = m.seq AND d.current_qty > 0
  LEFT JOIN item_master i ON i.seq = d.item_seq
 WHERE m.lpn_code = ? AND m.lifecycle_status = 'ACTIVE'
 ORDER BY i.item_code
"""


# ═══════════════════════════════════════════════════════════
# 물리적 통합 입고 (입고 규칙 2)
#   신규 입고분을 기존 R-LPN 에 합산한다. 새 LPN 을 발행하지 않는다.
#   실물도 같은 팔레트에 올리므로 위치는 변하지 않는다.
#
#   ※ init_qty 도 함께 늘린다. 라벨 표기와 어긋나므로
#     현장에서 라벨 재출력이 필요할 수 있다.
# ═══════════════════════════════════════════════════════════

#   파라미터 : lpn_master_seq, item_seq
SELECT_DETAIL_BY_ITEM = """
SELECT d.seq AS detail_seq, d.init_qty, d.current_qty,
       m.lpn_code, m.process_status, m.lifecycle_status, m.location_seq,
       i.item_code, i.item_name, i.uom
  FROM lpn_detail d
  JOIN lpn_master m  ON m.seq = d.lpn_master_seq
  JOIN item_master i ON i.seq = d.item_seq
 WHERE d.lpn_master_seq = ? AND d.item_seq = ?
"""

# 수량 합산
#   파라미터 : qty, qty, detail_seq
ADD_MERGE_QTY = """
UPDATE lpn_detail
   SET init_qty     = init_qty + ?,
       current_qty  = current_qty + ?,
       updated_date = sysdatetime()
 WHERE seq = ?
"""

# 입고 이력. 신규 입고분이므로 IN.
#   파라미터 : lpn_master_seq, item_seq, qty,
#              to_location_seq, device_id, worker_id
INSERT_TXN_MERGE_IN = """
INSERT INTO lpn_txn
      (txn_type, status, lpn_master_seq, item_seq, qty,
       to_location_seq, device_id, worker_id)
VALUES ('IN', 'DONE', ?, ?, ?, ?, ?, ?)
"""


# LPN 상세 — 수정 화면용. Multi-SKU 면 여러 행.
#   파라미터 : lpn_master_seq
SELECT_DETAIL_FOR_UPDATE = """
SELECT d.seq AS detail_seq, d.item_seq, d.init_qty, d.current_qty,
       i.item_code, i.item_name, i.uom,
       m.lpn_code, m.lpn_type, m.process_status, m.lifecycle_status,
       m.location_seq
  FROM lpn_detail d
  JOIN lpn_master m  ON m.seq = d.lpn_master_seq
  JOIN item_master i ON i.seq = d.item_seq
 WHERE m.seq = ?
 ORDER BY i.item_code
"""

# 자재 1행 수량 수정
#   파라미터 : init_qty, current_qty, detail_seq, lpn_master_seq
UPDATE_DETAIL_QTY_ONE = """
UPDATE d
   SET d.init_qty = ?, d.current_qty = ?, d.updated_date = SYSDATETIME()
  FROM lpn_detail d
 WHERE d.seq = ? AND d.lpn_master_seq = ?
"""

# 할당(PLAN)이 걸린 자재는 수량을 줄이면 지시가 깨진다
#   파라미터 : lpn_master_seq, item_seq
COUNT_ITEM_PLAN = """
SELECT ISNULL(SUM(qty), 0) FROM lpn_txn
 WHERE lpn_master_seq = ? AND item_seq = ?
   AND txn_type = 'PK' AND status = 'PLAN'
"""

#K-LPN 리스트 조회
SELECT_K_LPN_FOR_RFID = """
SELECT m.seq, m.lpn_code, m.rfid_yn, m.rfid_date,
       m.order_no, m.engine_no, m.proc_code, m.engine_seq_no,
       m.created_date,
       k.KIT_NO, k.STATION_NO, k.STATION_NAME, k.WORK_CENTER_NM
  FROM lpn_master m
  LEFT JOIN kit_table k ON k.SEQ = m.kit_seq
 WHERE m.lpn_type = 'K'
   AND m.lifecycle_status = 'ACTIVE'
   AND m.created_date >= ?
   AND m.created_date <  DATEADD(DAY, 1, ?)
 ORDER BY m.rfid_yn, m.created_date
"""

# K-LPN RFID Write
RFID_WRITE = """
UPDATE lpn_master
   SET rfid_yn = 1,
       rfid_date = SYSDATETIME()
 WHERE lpn_code = ?
   AND rfid_yn = 0
"""

# select kit by w-lpn
SELECT_W_LPN_INFO = """
SELECT m.seq        AS lpn_seq,
       m.lpn_code,
       m.lpn_type,
       m.process_status,
       k.SEQ        AS kit_seq,
       k.KIT_NO,
       k.MODEL,
       k.ENGINE_NO,
       k.ENGINE_SEQ_NO,
       k.PROC_CODE,
       k.WORK_CENTER_NM,
       k.PLAN_DATE,
       p.PICK_NO
  FROM lpn_master m
  LEFT JOIN kit_table k ON k.SEQ = m.kit_seq
  OUTER APPLY (
      SELECT TOP 1 x.PICK_NO
        FROM pick_table x
       WHERE x.KIT_SEQ = k.SEQ
         AND x.LIFECYCLE_STATUS = 'ACTIVE'
         AND x.SRC_TYPE <> 'URGENT'
       ORDER BY x.SEQ
  ) p
 WHERE m.lpn_code = ?
   AND m.lifecycle_status = 'ACTIVE'
"""

