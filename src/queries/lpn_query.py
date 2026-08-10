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

SELECT_BY_CODE_LPN = SELECT_BASE + """
WHERE m.lpn_code = ?
"""

SELECT_BY_SEQ = SELECT_BASE + """
WHERE m.seq = ?
"""

# 발행 대기 목록 — 등록만 되고 라벨 미출력
SELECT_UNPRINTED_LPN = SELECT_BASE + """
WHERE m.process_status = 'CREATED'
  AND m.lifecycle_status = 'ACTIVE'
ORDER BY m.seq
"""

# 적치 대기 목록 — 라벨은 나왔으나 위치 미확정
SELECT_UNBOUND_LPN = SELECT_BASE + """
WHERE m.process_status = 'PRINTED'
  AND m.lifecycle_status = 'ACTIVE'
ORDER BY m.seq
"""

SELECT_R_LPN = SELECT_BASE + """
WHERE m.lpn_type = 'R'
  AND m.lifecycle_status = 'ACTIVE'
ORDER BY m.lpn_code
"""

SELECT_R_LPN_BY_CODE = SELECT_BASE + """
WHERE m.lpn_type = 'R' AND m.lpn_code = ?
"""

SELECT_ITEM_BY_CODE = """
SELECT seq, item_code, item_name, uom, washing_yn
FROM item_master
WHERE item_code = ? AND use_yn = 1
"""


# ── 채번 ────────────────────────────────────────────────────
#   LPN 코드 = [타입 1] + [YYMMDD 6] + [일련번호 5] = 12자리
#   DB 저장은 하이픈 없음. 화면/라벨 표기 시에만 하이픈 삽입.
#   타입별 + 일자별 독립 채번, 일자 변경 시 00001 로 리셋.
#   파라미터 : lpn_type, yymmdd, lpn_type, yymmdd, lpn_type, yymmdd
NEXT_LPN_NO = """
SET NOCOUNT ON;
DECLARE @d  CHAR(6) = CONVERT(CHAR(6), GETDATE(), 12);
DECLARE @no INT;

UPDATE lpn_seq WITH (UPDLOCK, SERIALIZABLE)
   SET @no = last_no = last_no + 1
 WHERE lpn_type = ? AND yymmdd = @d;

IF @no IS NULL
BEGIN
    INSERT INTO lpn_seq (lpn_type, yymmdd, last_no) VALUES (?, @d, 1);
    SET @no = 1;
END

SELECT ? + @d + RIGHT('0000' + CAST(@no AS VARCHAR(5)), 5) AS lpn_code,
       @no AS seq_no;
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

UPDATE_PRINTED_BY_CODE = """
UPDATE lpn_master
   SET process_status = 'PRINTED',
       print_yn       = 1,
       updated_date   = SYSDATETIME()
 WHERE lpn_code = ?
   AND process_status = 'CREATED'
   AND lifecycle_status = 'ACTIVE'
"""

# 라벨 재출력 — 상태는 그대로, 훼손·미출력 대응
REPRINT_BY_SEQ = """
UPDATE lpn_master
   SET print_yn = 1, updated_date = SYSDATETIME()
 WHERE seq = ? AND lifecycle_status = 'ACTIVE'
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

# 등록 취소 — 실물과 연결되기 전(CREATED/PRINTED)에만 허용
CANCEL_LPN = """
UPDATE lpn_master
   SET process_status   = 'VOID',
       lifecycle_status = 'INACTIVE',
       updated_date     = SYSDATETIME()
 WHERE seq = ?
   AND process_status IN ('CREATED', 'PRINTED')
   AND lifecycle_status = 'ACTIVE'
"""