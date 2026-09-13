# ═══════════════════════════════════════════════════════════
# 공급 순서 (kit_table.DELIVERY_SEQ)
#   AMR 투입 순서이자 피킹·키팅 순서.
#   호기가 섞인 작업 큐이므로 proc_master.proc_order 와는 무관하다.
#
#   ※ 10 단위로 부여한다.
#     분할 기능이 붙었을 때 사이 값(15, 25)으로 끼워넣기 위함.
#     화면에는 1·2·3 으로 보여주고 내부값만 10 단위로 쓴다.
#
#   ※ 작업이 시작된 건(KITTING 이후)은 순서를 바꾸지 않는다.
# ═══════════════════════════════════════════════════════════

# 순서 변경. 작업 시작 전인 건만.
#   파라미터 : delivery_seq, kit_seq
UPDATE_DELIVERY_SEQ = """
UPDATE kit_table
   SET DELIVERY_SEQ = ?, UPDATED_DATE = sysdatetime()
 WHERE SEQ = ?
   AND LIFECYCLE_STATUS = 'ACTIVE'
   AND STATUS IN ('WAIT','PICKING')
"""

# 변경 대상 검증 — 같은 날짜인지, 이미 착수했는지
#   파라미터 : kit_seq
SELECT_KIT_ORDER_INFO = """
SELECT SEQ, KIT_NO, PLAN_DATE, DELIVERY_SEQ, STATUS, LIFECYCLE_STATUS
  FROM kit_table WHERE SEQ = ?
"""

# 확정 시 부여할 다음 순번. 그날 마지막 + 10.
#   파라미터 : plan_date
NEXT_DELIVERY_SEQ = """
SELECT ISNULL(MAX(DELIVERY_SEQ), 0) + 10
  FROM kit_table
 WHERE PLAN_DATE = ? AND LIFECYCLE_STATUS = 'ACTIVE'
"""

# 분할 시 두 순번 사이 값. 여유가 없으면 NULL.
#   파라미터 : base_seq, plan_date, base_seq
NEXT_SPLIT_SEQ = """
SELECT CASE WHEN nxt IS NULL      THEN base + 10
            WHEN nxt - base > 1   THEN base + (nxt - base) / 2
            ELSE NULL END AS split_seq
  FROM (
      SELECT ? AS base,
             (SELECT MIN(DELIVERY_SEQ) FROM kit_table
               WHERE PLAN_DATE = ? AND LIFECYCLE_STATUS = 'ACTIVE'
                 AND DELIVERY_SEQ > ?) AS nxt
  ) x
"""

# 간격 재정렬. 현재 순서를 유지한 채 10 단위로 다시 매긴다.
#   분할로 사이 값이 꽉 찼을 때 호출.
#   파라미터 : plan_date
RENUMBER_DELIVERY_SEQ = """
WITH x AS (
    SELECT SEQ, ROW_NUMBER() OVER (ORDER BY DELIVERY_SEQ, SEQ) * 10 AS new_seq
      FROM kit_table
     WHERE PLAN_DATE = ? AND LIFECYCLE_STATUS = 'ACTIVE'
       AND STATUS IN ('WAIT','PICKING')
)
UPDATE k
   SET k.DELIVERY_SEQ = x.new_seq, k.UPDATED_DATE = sysdatetime()
  FROM kit_table k JOIN x ON x.SEQ = k.SEQ
"""