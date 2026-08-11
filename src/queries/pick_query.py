SELECT_ALL = """
SELECT p.seq,
       p.kit_seq,
       p.order_no,
       k.engine_seq_no,
       k.engine_no,
       k.proc_code,
       k.work_center_nm,
       k.delivery_seq,
       p.item_code,
       p.item_name,
       p.req_qty,
       p.picked_qty,
       p.uom,
       p.lpn_type,
       p.status
  FROM PICK_TABLE p
  JOIN KIT_TABLE  k ON k.seq = p.kit_seq
 WHERE p.status = 'ISSUED'
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY k.delivery_seq, p.item_code
"""

SELECT_ALL_GROUP_KIT = """
SELECT p.seq,
       p.kit_seq,
       p.order_no,
       k.engine_seq_no,
       k.engine_no,
       k.proc_code,
       k.work_center_nm,
       k.delivery_seq,
       k.status   AS kit_status,
       k.hold_yn,
       p.item_code,
       p.item_name,
       p.req_qty,
       p.picked_qty,
       p.uom,
       p.lpn_type,
       p.status
  FROM PICK_TABLE p
  JOIN KIT_TABLE  k ON k.seq = p.kit_seq
 WHERE p.status = 'ISSUED'
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY k.engine_seq_no,
          k.delivery_seq,
          CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          p.item_code
"""


SELECT_BY_SEQ_GROUP_KIT = """
SELECT p.seq,
       p.kit_seq,
       p.order_no,
       k.engine_seq_no,
       k.engine_no,
       k.proc_code,
       k.work_center_nm,
       k.delivery_seq,
       k.status   AS kit_status,
       k.hold_yn,
       p.item_code,
       p.item_name,
       p.req_qty,
       p.picked_qty,
       p.uom,
       p.lpn_type,
       p.status
  FROM PICK_TABLE p
  JOIN KIT_TABLE  k ON k.seq = p.kit_seq
 WHERE p.kit_seq = ?
   AND p.status = 'ISSUED'
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          p.item_code
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


INSERT_LPN_MASTER = """
INSERT INTO lpn_master
    (lpn_code, lpn_type, process_status, lifecycle_status,
     print_yn, split_yn, kit_seq, order_no, engine_no, proc_code, engine_seq_no)
OUTPUT INSERTED.seq
VALUES (?, ?, 'CREATED', 'ACTIVE', 0, 0, ?, ?, ?, ?, ?);
"""

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