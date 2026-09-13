# -*- coding: utf-8 -*-
"""공정 마스터 서비스

  공정은 ERP 지시를 받을 때 자동으로 등록된다(src_type = AUTO).
  이 화면에서는 순서만 바꾼다 — 여기서 정한 순서대로 피킹리스트가 발행된다.
"""
from src.queries.master import proc_master_query as q
from src.db.connection import query, transaction
from src.logger.logger import get_logger
from src.common import engine_model as em

logger = get_logger("svc")


def get_model_list() -> list[dict]:
    """좌측 모델 목록. engine_model.ini 의 라인 정보를 붙인다."""
    rows = query(q.SELECT_MODEL_LIST)
    for r in rows:
        try:
            conf = em.get_model(r["model"])
            r["line_name"] = conf["line_name"]
            r["line_type"] = conf["line_type"]
        except ValueError:
            r["line_name"] = "미등록 모델"
            r["line_type"] = None
    return rows


def get_proc_list(model: str) -> dict:
    """모델의 공정 목록. 순서대로."""
    name = (model or "").strip()
    if not name:
        raise ValueError("모델을 선택해 주세요")

    rows = query(q.SELECT_PROC_LIST, (name,))

    try:
        line_name = em.get_model(name)["line_name"]
    except ValueError:
        line_name = "미등록 모델"

    return {
        "model":     name,
        "line_name": line_name,
        "items": [{
            "seq":        r["seq"],
            "erp_code":   r["erp_code"],
            "proc_code":  r["proc_code"],
            "proc_name":  r["proc_name"],
            "proc_order": r["proc_order"],
            "src_type":   r["src_type"],
            "updated_date": r["updated_date"],
        } for r in rows],
        "total":      len(rows),
        "manual_cnt": sum(1 for r in rows if r["src_type"] == "MANUAL"),
    }


def update_order(model: str, items: list[dict],
                 worker_id: str | None = None) -> dict:
    """드래그 결과 일괄 저장.

    프론트가 화면 순서대로 (i+1)*10 을 계산해 보낸다.
    다른 모델의 공정이 섞여 들어오면 거부한다.
    """
    name = (model or "").strip()
    if not items:
        raise ValueError("변경할 대상이 없습니다")

    seqs = [i["seq"] for i in items]
    if len(seqs) != len(set(seqs)):
        raise ValueError("중복된 공정이 포함되어 있습니다")

    orders = [i["proc_order"] for i in items]
    if len(orders) != len(set(orders)):
        raise ValueError("순서가 중복됩니다")

    with transaction() as cur:
        changed = 0
        for it in items:
            cur.execute(q.SELECT_PROC_MODEL, (it["seq"],))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"존재하지 않는 공정입니다: {it['seq']}")
            if row[0] != name:
                raise ValueError(f"다른 모델의 공정이 포함되어 있습니다: {row[0]}")

            cur.execute(q.UPDATE_PROC_ORDER,
                        (it["proc_order"], worker_id, it["seq"]))
            changed += 1 if cur.rowcount else 0

    if changed == 0:
        raise ValueError("변경된 내용이 없습니다")

    logger.info("공정 순서 변경 - %s %s건 by=%s", name, changed, worker_id)
    return {"model": name, "updated_cnt": changed}