
SELECT_ALL = """
SELECT p.seq,
       p.kit_seq,
       p.order_no,
       k.mes_seq_no,
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
 WHERE p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY k.delivery_seq, p.item_code
"""

SELECT_ALL_GROUP_KIT = """
SELECT p.seq,
       p.kit_seq,
       p.order_no,
       k.mes_seq_no,
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
 WHERE p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY k.mes_seq_no,
          k.delivery_seq,
          CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          p.item_code
"""


SELECT_ALL_BY_KIT_SEQ = """
SELECT p.seq,
       p.kit_seq,
       p.order_no,
       k.mes_seq_no,
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
   AND p.lifecycle_status = 'ACTIVE'
   AND k.lifecycle_status = 'ACTIVE'
 ORDER BY CASE WHEN p.lpn_type = 'W' THEN 0 ELSE 1 END,
          p.item_code
"""