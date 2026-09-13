# -*- coding: utf-8 -*-
"""공정 마스터 SQL

  ERP 지시 수신 시 자동 등록되고(src_type = AUTO),
  화면에서는 순서만 바꾼다. 공정 추가·삭제는 하지 않는다.
"""

# 좌측 모델 목록
SELECT_MODEL_LIST = """
SELECT model,
       COUNT(*)          AS proc_cnt,
       MAX(updated_date) AS updated_date
  FROM proc_master
 WHERE use_yn = 1
 GROUP BY model
 ORDER BY model
"""

# 우측 공정 목록 — 순서대로
#   파라미터 : model
SELECT_PROC_LIST = """
SELECT p.seq, p.model, p.erp_code, p.proc_code, p.proc_name,
       p.proc_order, p.src_type, p.updated_date, p.worker_id
  FROM proc_master p
 WHERE p.model = ? AND p.use_yn = 1
 ORDER BY p.proc_order, p.proc_code
"""

# 순서 변경 — 드래그 결과
#   파라미터 : proc_order, worker_id, seq
UPDATE_PROC_ORDER = """
UPDATE proc_master
   SET proc_order = ?,
       src_type   = 'MANUAL',
       worker_id  = ?,
       updated_date = SYSDATETIME()
 WHERE seq = ? AND use_yn = 1
"""

# 같은 모델인지 확인 — 다른 모델 공정이 섞여 들어오는 것을 막는다
#   파라미터 : seq
SELECT_PROC_MODEL = """
SELECT model FROM proc_master WHERE seq = ? AND use_yn = 1
"""

# ── 가공용 — 지시 수신 시 자동 등록 ─────────────────────────
#   파라미터 : model, erp_code, proc_code, proc_name, proc_order,
#              model, proc_code
INSERT_PROC_IF_MISSING = """
INSERT INTO proc_master
    (model, erp_code, proc_code, proc_name, proc_order, src_type)
SELECT ?, ?, ?, ?, ?, 'AUTO'
 WHERE NOT EXISTS (
       SELECT 1 FROM proc_master
        WHERE model = ? AND proc_code = ? AND use_yn = 1)
"""