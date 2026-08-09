# ═══════════════════════════════════════════════════════════
# rack_master 관리 쿼리
#   랙 마스터 CRUD 전용. 적치 현황(LPN/자재)은 랙현황조회에서 담당.
#   ※ rows 는 T-SQL 예약어이므로 반드시 [rows] 로 감쌀 것
# ═══════════════════════════════════════════════════════════

# ── 목록 공통 SELECT ────────────────────────────────────────
#   zone_master JOIN     : 화면에 zone_seq 숫자 대신 구역명 표시
#   location_master LEFT : 셀이 없는 랙도 목록에 나오도록
SELECT_BASE = """
SELECT
    r.seq,
    r.rack_code,
    r.rack_name,
    r.zone_seq,
    z.zone_code,
    z.zone_name,
    r.[rows],
    r.cols,
    r.enable_yn,
    r.created_date,
    r.updated_date,
    COUNT(l.seq)                                     AS location_cnt,
    SUM(CASE WHEN l.enable_yn = 1 THEN 1 ELSE 0 END) AS usable_cnt
FROM rack_master r
JOIN zone_master z
    ON z.seq = r.zone_seq
LEFT JOIN location_master l
    ON l.rack_seq = r.seq
"""

# 집계함수를 쓰므로 SELECT 한 일반 컬럼은 전부 GROUP BY 필요
GROUP_ORDER = """
GROUP BY
    r.seq, r.rack_code, r.rack_name, r.zone_seq,
    z.zone_code, z.zone_name,
    r.[rows], r.cols, r.enable_yn,
    r.created_date, r.updated_date
ORDER BY z.zone_code, r.rack_code
"""


# ── 조회 ───────────────────────────────────────────────────
SELECT_ALL = SELECT_BASE + GROUP_ORDER

# 랙코드 / 랙명 검색   파라미터 : %검색어%, %검색어%
SELECT_BY_CODE = SELECT_BASE + """
WHERE r.rack_code LIKE ?
   OR r.rack_name LIKE ?
""" + GROUP_ORDER

# 구역별 조회   파라미터 : zone_seq
SELECT_BY_ZONE = SELECT_BASE + """
WHERE r.zone_seq = ?
""" + GROUP_ORDER


# ── 상세 : 랙 기본정보 + 셀 목록 ─────────────────────────────
#   row_no DESC : 상단이 화면 위로 오도록 (1단 = 최하단 기준)
SELECT_BY_SEQ = """
SELECT
    r.seq,
    r.rack_code,
    r.rack_name,
    r.zone_seq,
    z.zone_code,
    z.zone_name,
    r.[rows],
    r.cols,
    r.enable_yn,
    r.created_date,
    r.updated_date,

    l.seq       AS location_seq,
    l.location_code,
    l.row_no,
    l.col_no,
    l.max_weight,
    l.enable_yn AS location_enable_yn
FROM rack_master r
JOIN zone_master z
    ON z.seq = r.zone_seq
LEFT JOIN location_master l
    ON l.rack_seq = r.seq
WHERE r.seq = ?
ORDER BY l.row_no DESC, l.col_no
"""


# ── 등록 / 수정 ─────────────────────────────────────────────
INSERT = """
INSERT INTO rack_master
    (rack_code, rack_name, zone_seq, [rows], cols, enable_yn, created_date)
VALUES (?, ?, ?, ?, ?, 1, SYSDATETIME())
"""

UPDATE = """
UPDATE rack_master
   SET rack_code    = ?,
       rack_name    = ?,
       zone_seq     = ?,
       [rows]       = ?,
       cols         = ?,
       enable_yn    = ?,
       updated_date = SYSDATETIME()
 WHERE seq = ?
"""


# ── 중복 검사 ───────────────────────────────────────────────
EXISTS_CODE = """
SELECT 1 FROM rack_master WHERE rack_code = ?
"""

# 수정 시 자기 자신 제외   파라미터 : rack_code, seq
EXISTS_CODE_EXCEPT_SELF = """
SELECT 1 FROM rack_master WHERE rack_code = ? AND seq <> ?
"""


# ── 사용중지 / 삭제 ─────────────────────────────────────────
#   lpn_txn 이 로케이션을 이력으로 참조하므로 사용중지가 기본.
#   물리삭제는 하위 셀이 하나도 없을 때만 허용한다.
DISABLE = """
UPDATE rack_master
   SET enable_yn = 0, updated_date = SYSDATETIME()
 WHERE seq = ?
"""

CHECK_DELETABLE = """
SELECT COUNT(*) AS location_cnt
  FROM location_master
 WHERE rack_seq = ?
"""

DELETE = """
DELETE FROM rack_master WHERE seq = ?
"""

INSERT_LOCATIONS = """
;WITH nums AS (
    SELECT TOP (100) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n
      FROM sys.all_objects
)
INSERT INTO location_master
    (location_code, rack_seq, row_no, col_no, enable_yn)
SELECT R.rack_code + '-'
     + RIGHT('0' + CAST(RW.n AS VARCHAR(2)), 2) + '-'
     + RIGHT('0' + CAST(CL.n AS VARCHAR(2)), 2),
       R.seq, RW.n, CL.n, 1
  FROM rack_master R
 CROSS JOIN (SELECT n FROM nums WHERE n <= ?) RW
 CROSS JOIN (SELECT n FROM nums WHERE n <= ?) CL
 WHERE R.seq = ?
   AND NOT EXISTS (SELECT 1 FROM location_master L
                    WHERE L.rack_seq = R.seq
                      AND L.row_no = RW.n AND L.col_no = CL.n)
"""

# 등록 직후 seq 회수
INSERT_RETURN_SEQ = """
SELECT SCOPE_IDENTITY() AS seq
"""


EXISTS_CODE_SEQ = """
SELECT seq FROM rack_master WHERE rack_code = ?
"""