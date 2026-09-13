# ═══════════════════════════════════════════════════════════
# 지시번호 채번
#   PIK + YYMMDD + 4자리 = 13자리   예) PIK2608130001
#   KIT + YYMMDD + 4자리 = 13자리   예) KIT2608130001
#   유형별·일자별 독립. 일자 변경 시 0001 로 리셋.
#   파라미터 : doc_type x 3
# ═══════════════════════════════════════════════════════════
NEXT_DOC_NO = """
SET NOCOUNT ON;
DECLARE @d  CHAR(6) = CONVERT(CHAR(6), GETDATE(), 12);
DECLARE @no INT;

UPDATE doc_seq WITH (UPDLOCK, SERIALIZABLE)
   SET @no = last_no = last_no + 1
 WHERE doc_type = ? AND yymmdd = @d;

IF @no IS NULL
BEGIN
    INSERT INTO doc_seq (doc_type, yymmdd, last_no) VALUES (?, @d, 1);
    SET @no = 1;
END

SELECT ? + @d + RIGHT('000' + CAST(@no AS VARCHAR(4)), 4) AS doc_no,
       @no AS seq_no;
"""

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


# ═══════════════════════════════════════════════════════════
# 상태 전이 이력
#   lpn_txn 은 '물건의 움직임' 을, 이 테이블은 '상태의 변화' 를 남긴다.
#   Temporal Table 과 달리 worker_id 가 남는 것이 핵심.
#   ※ 상태를 바꾸는 모든 서비스에서 호출해야 이력이 비지 않는다.
# ═══════════════════════════════════════════════════════════

#   파라미터 : table_name, row_seq, doc_no, from_status, to_status,
#              worker_id, device_id, remark
INSERT_STATUS_LOG = """
INSERT INTO status_log
      (table_name, row_seq, doc_no, from_status, to_status,
       worker_id, device_id, remark)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""
