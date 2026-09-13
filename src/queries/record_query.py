# -*- coding: utf-8 -*-
"""src/queries/record_query.py — 이력 적재 SQL

세척 AMR 이력. ACS / QR PC 가 상태 전이마다 보내는 값을 그대로 남긴다.
status 에 CHECK 제약을 걸지 않는다 — 상태 정의의 주인이 저쪽이므로
값이 하나 추가될 때마다 INSERT 가 터지면 이력이 아예 안 쌓인다.
"""

# 세척 AMR 이력 적재
#   파라미터 : job_type, pallet_no, model, hogi,
#              w_lpn_list, status, status_date, remark
INSERT_WASH_LOG = """
INSERT INTO wash_log
    (job_type, pallet_no, model, engine_no,
     w_lpn_list, status, status_date, remark)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


# 세척 AMR 이력 조회 — 기간
#   파라미터 : date_from, date_to
# SELECT_WASH_LOG = """
# SELECT seq, job_type, pallet_no, model, engine_no,
#        w_lpn_list, status, status_date, remark
#   FROM wash_log
#  WHERE status_date >= ?
#    AND status_date <  DATEADD(DAY, 1, ?)
#  ORDER BY status_date DESC, seq DESC
# """

# 물류 AMR 이력 적재
#   파라미터 : k_lpn_code, kit_seq, kit_no, station_no, station_name,
#              dest_code, model, engine_no, status, status_date, remark
INSERT_LOGISTICS_LOG = """
INSERT INTO logistics_log
    (k_lpn_code, kit_seq, kit_no, station_no, station_name,
     dest_code, model, engine_no, status, status_date, remark)
OUTPUT INSERTED.seq
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# 기간 조회
#   파라미터 : date_from, date_to
# SELECT_LOGISTICS_LOG = """
# SELECT seq, k_lpn_code, kit_seq, kit_no, station_no, station_name,
#        dest_code, model, engine_no, status, status_date, remark
#   FROM logistics_log
#  WHERE status_date >= ?
#    AND status_date <  DATEADD(DAY, 1, ?)
#  ORDER BY status_date DESC, seq DESC
# """
