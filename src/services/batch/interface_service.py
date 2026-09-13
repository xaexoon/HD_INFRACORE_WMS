from src.queries.batch import interface_query
from src.queries.master import proc_master_query as pmq
from src.db.connection import query, transaction
from src.logger.logger import get_logger
from src.services import common_service
from src.common import engine_model as em

logger = get_logger("batch.if")


def sync_orders() -> dict:
    """ERP I/F 폴링 가공. 미처리분이 없으면 즉시 종료."""
    targets = query(interface_query.SELECT_UNPROCESSED)
    if not targets:
        return {"total": 0, "success": 0, "skipped": 0, "failed": 0}

    ok = skip = fail = 0
    for t in targets:
        order_no = t["AUFNR"]
        try:
            cnt = _process_order(order_no)
            if cnt is None:
                skip += 1
            else:
                ok += 1
        except Exception as e:
            fail += 1
            logger.error("가공 실패 - order=%s : %s", order_no, e)
            _mark_error(order_no, str(e))

    logger.info("I/F 가공 - 총 %s (성공 %s / 스킵 %s / 실패 %s)",
                len(targets), ok, skip, fail)
    return {"total": len(targets), "success": ok, "skipped": skip, "failed": fail}


def _proc_key(v):
    """공정번호 정렬. 숫자면 숫자순, 아니면 문자순."""
    s = str(v).strip()
    return (0, int(s)) if s.isdigit() else (1, s)


def _process_order(order_no: str) -> int | None:
    """오더 1건 가공. 착수된 오더는 갱신하지 않고 None 반환."""
    with transaction() as cur:
        # 최신 전송회차
        cur.execute(interface_query.SELECT_LATEST_IF, (order_no,))
        head = cur.fetchone()
        if head is None:
            raise RuntimeError("헤더를 찾을 수 없습니다")

        ifseq, ifdat, iftim, engine_no, seqno, gstrs, model = head

        # 모델 설정. engine_model.ini 에 없으면 여기서 멈춘다 —
        # 방산 모델이 누락된 채 대차 없이 흘러가는 것을 막기 위함.
        conf = em.get_model(model)

        # 착수 여부 — 진행 중이면 갱신 금지 (담당자 확정 사항)
        cur.execute(interface_query.COUNT_IN_PROGRESS, (order_no,))
        if cur.fetchone()[0] > 0:
            logger.warning("착수된 오더 — 갱신 스킵: %s (회차 %s %s)",
                           order_no, ifdat, iftim)
            cur.execute(interface_query.MARK_SUCCESS, (ifseq, order_no))
            cur.execute(interface_query.MARK_SUCCESS_D, (ifdat, iftim, order_no))
            return None

        # 기존 미착수 라인 무효화 후 재생성
        cur.execute(interface_query.INACTIVE_OLD_PICK, (order_no,))

        cur.execute(interface_query.INSERT_PICK_FROM_ORDER,
                    (ifseq, engine_no, seqno, gstrs, model,
                     order_no, ifdat, iftim))
        inserted = cur.rowcount

        cur.execute(interface_query.SELECT_PROC_LIST, (order_no, ifdat, iftim))
        procs = [v for (v,) in cur.fetchall()]

        # 공정 마스터 자동 등록 — 대형·초대형만.
        # 방산은 대차 배정이 필요해 엑셀로 사전 등록한다(auto_proc = false).
        # 이미 있는 공정은 건너뛰므로 화면에서 바꾼 순서를 덮지 않는다.
        added = 0
        if conf["auto_proc"]:
            for n, vornr in enumerate(sorted(procs, key=_proc_key), 1):
                cur.execute(pmq.INSERT_PROC_IF_MISSING,
                            (model, vornr, vornr, f"공정 {vornr}", n * 10,
                             model, vornr))
                added += cur.rowcount

        for vornr in procs:
            pick_no = common_service.make_doc_no(cur, "PIK")
            cur.execute(interface_query.UPDATE_PICK_NO, (pick_no, order_no, vornr))

        cur.execute(interface_query.MARK_SUCCESS, (ifseq, order_no))
        cur.execute(interface_query.MARK_SUCCESS_D, (ifdat, iftim, order_no))

    logger.info("가공 완료 - order=%s 모델=%s(%s) 회차=%s %s → %s행 / 공정 %s(신규 %s)",
                order_no, model, conf["line_name"], ifdat, iftim,
                inserted, len(procs), added)
    return inserted


def _mark_error(order_no: str, msg: str) -> None:
    with transaction() as cur:
        cur.execute(interface_query.MARK_ERROR, (msg[:1000], order_no))