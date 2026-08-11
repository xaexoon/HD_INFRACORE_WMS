# ═══════════════════════════════════════════════════════════
# 이력 조회 쿼리 (history)
#   lpn_txn 이 재고 원장. 여기서 모든 이력이 나온다.
#
#   A. 기간별 통합  — 화면 기본. 날짜 + 유형 + 검색어
#   B. LPN 추적     — 한 LPN 의 생애 (입고 ~ 소진)
#   C. 자재 추적    — 자재가 어느 엔진에 들어갔나
#
#   ※ 용어 : 팔렛 통합의 소스/타겟과 혼동되지 않도록
#            lpn_txn 의 이동 방향은 from_ / to_ 로 표기한다.
#              m  = 출발 LPN (lpn_master_seq)
#              tm = 도착 LPN (to_lpn_seq)
# ═══════════════════════════════════════════════════════════


# ── 공통 SELECT ─────────────────────────────────────────────
#   대표 LPN = 도착 LPN(있으면) / 없으면 출발 LPN
#     IN : 도착 없음 → R-LPN 이 대표
#     PK : R-LPN → W/D-LPN, 도착인 W/D-LPN 이 대표
#   PLAN 행은 아직 실적이 아니므로 기본 조회에서 제외한다.
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
LEFT JOIN location_master fl ON fl.seq = t.from_location_seq
LEFT JOIN rack_master     fr ON fr.seq = fl.rack_seq
LEFT JOIN zone_master     fz ON fz.seq = fr.zone_seq
LEFT JOIN location_master tl ON tl.seq = t.to_location_seq
LEFT JOIN rack_master     tr ON tr.seq = tl.rack_seq
LEFT JOIN zone_master     tz ON tz.seq = tr.zone_seq
WHERE t.status = 'DONE'
  AND t.txn_date >= ?
  AND t.txn_date <  DATEADD(DAY, 1, ?)
"""

ORDER_BY = """
ORDER BY t.txn_date DESC, ISNULL(tm.seq, m.seq), t.seq
"""


# ── A-1. 기간별 전체 ────────────────────────────────────────
#   파라미터 : date_from, date_to
SELECT_BY_PERIOD = SELECT_BASE + ORDER_BY

# 유형 필터 추가   파라미터 : date_from, date_to, txn_type
SELECT_BY_TYPE = SELECT_BASE + """
  AND t.txn_type = ?
""" + ORDER_BY

# 대표 LPN 유형 필터 (W / D / R / K)
#   파라미터 : date_from, date_to, lpn_type
SELECT_BY_LPN_TYPE = SELECT_BASE + """
  AND ISNULL(tm.lpn_type, m.lpn_type) = ?
""" + ORDER_BY


# ── A-2. 검색어 ────────────────────────────────────────────
#   LPN 코드 / 로케이션 코드 / 자재코드 / 자재명 / 호기를 한 번에 훑는다.
#   파라미터 : date_from, date_to, like x 7
SELECT_BY_KEYWORD = SELECT_BASE + """
  AND (m.lpn_code       LIKE ?
    OR tm.lpn_code      LIKE ?
    OR fl.location_code LIKE ?
    OR tl.location_code LIKE ?
    OR i.item_code      LIKE ?
    OR i.item_name      LIKE ?
    OR m.engine_no      LIKE ?)
""" + ORDER_BY

# 유형 + 검색어   파라미터 : date_from, date_to, txn_type, like x 7
SELECT_BY_TYPE_KEYWORD = SELECT_BASE + """
  AND t.txn_type = ?
  AND (m.lpn_code       LIKE ?
    OR tm.lpn_code      LIKE ?
    OR fl.location_code LIKE ?
    OR tl.location_code LIKE ?
    OR i.item_code      LIKE ?
    OR i.item_name      LIKE ?
    OR m.engine_no      LIKE ?)
""" + ORDER_BY


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


# ── C. 자재 추적 — 어느 엔진/공정에 들어갔나 ────────────────
#   파라미터 : item_code, date_from, date_to
SELECT_BY_ITEM = """
SELECT
    t.seq        AS txn_seq,
    t.txn_type,
    t.status,
    t.qty,
    t.txn_date,
    t.worker_id,

    i.item_code, i.item_name,

    m.lpn_code        AS from_lpn_code,
    m.lpn_type        AS from_lpn_type,
    tm.lpn_code       AS to_lpn_code,
    tm.lpn_type       AS to_lpn_type,

    tm.order_no, tm.engine_no, tm.proc_code, tm.engine_seq_no,
    fl.location_code  AS from_location_code,
    tl.location_code  AS to_location_code
FROM lpn_txn t
JOIN item_master i       ON i.seq = t.item_seq
JOIN lpn_master m        ON m.seq = t.lpn_master_seq
LEFT JOIN lpn_master tm  ON tm.seq = t.to_lpn_seq
LEFT JOIN location_master fl ON fl.seq = t.from_location_seq
LEFT JOIN location_master tl ON tl.seq = t.to_location_seq
WHERE i.item_code = ?
  AND t.status = 'DONE'
  AND t.txn_date >= ?
  AND t.txn_date <  DATEADD(DAY, 1, ?)
ORDER BY t.txn_date DESC, t.seq DESC
"""


# ── 유형 코드 목록 — 상단 셀렉트박스용 ──────────────────────
SELECT_TXN_TYPES = """
SELECT code, code_name, sort_order
  FROM common_code
 WHERE group_code = 'TXN_TYPE' AND use_yn = 1
 ORDER BY sort_order
"""


# ── 이력 단건 상세 — 목록에서 행 클릭 시 ────────────────────
#   기간/상태 필터 없이 seq 로 직접 조회. PLAN 행도 조회 가능.
#   파라미터 : seq
SELECT_BY_SEQ = """
SELECT
    t.seq        AS txn_seq,
    t.txn_type,
    t.status,
    t.qty,
    t.txn_date,
    t.device_id,
    t.worker_id,
    t.PICK_SEQ,

    m.seq              AS from_lpn_seq,
    m.lpn_code         AS from_lpn_code,
    m.lpn_type         AS from_lpn_type,
    m.process_status   AS from_process_status,
    m.lifecycle_status AS from_lifecycle_status,

    tm.seq             AS to_lpn_seq,
    tm.lpn_code        AS to_lpn_code,
    tm.lpn_type        AS to_lpn_type,
    tm.process_status  AS to_process_status,
    t.to_detail_seq,

    i.seq              AS item_seq,
    i.item_code,
    i.item_name,
    i.uom,
    i.washing_yn,

    fl.location_code   AS from_location_code,
    fr.rack_code       AS from_rack_code,
    fz.zone_name       AS from_zone_name,
    tl.location_code   AS to_location_code,
    tr.rack_code       AS to_rack_code,
    tz.zone_name       AS to_zone_name,

    ISNULL(tm.order_no,      m.order_no)      AS order_no,
    ISNULL(tm.engine_no,     m.engine_no)     AS engine_no,
    ISNULL(tm.proc_code,     m.proc_code)     AS proc_code,
    ISNULL(tm.engine_seq_no, m.engine_seq_no) AS engine_seq_no
FROM lpn_txn t
JOIN lpn_master m        ON m.seq = t.lpn_master_seq
LEFT JOIN lpn_master tm  ON tm.seq = t.to_lpn_seq
LEFT JOIN item_master i  ON i.seq = t.item_seq
LEFT JOIN location_master fl ON fl.seq = t.from_location_seq
LEFT JOIN rack_master     fr ON fr.seq = fl.rack_seq
LEFT JOIN zone_master     fz ON fz.seq = fr.zone_seq
LEFT JOIN location_master tl ON tl.seq = t.to_location_seq
LEFT JOIN rack_master     tr ON tr.seq = tl.rack_seq
LEFT JOIN zone_master     tz ON tz.seq = tr.zone_seq
WHERE t.seq = ?
"""


# ── 연관 이력 — 같은 피킹 지시로 묶인 거래 ──────────────────
#   PICK_SEQ 가 같은 행들. 분할 할당(한 자재를 여러 R-LPN 에서)
#   상황에서 "이 지시로 뭐가 더 나갔나"를 본다.
#   파라미터 : pick_seq
SELECT_BY_PICK_SEQ = """
SELECT
    t.seq        AS txn_seq,
    t.txn_type,
    t.status,
    t.qty,
    t.txn_date,
    t.worker_id,

    m.lpn_code        AS from_lpn_code,
    tm.lpn_code       AS to_lpn_code,
    i.item_code, i.item_name,
    fl.location_code  AS from_location_code
FROM lpn_txn t
JOIN lpn_master m        ON m.seq = t.lpn_master_seq
LEFT JOIN lpn_master tm  ON tm.seq = t.to_lpn_seq
LEFT JOIN item_master i  ON i.seq = t.item_seq
LEFT JOIN location_master fl ON fl.seq = t.from_location_seq
WHERE t.PICK_SEQ = ?
ORDER BY t.txn_date, t.seq
"""