from src.queries import kit_query
from src.db.connection import query, transaction
from src.logger.logger import get_logger
from src.services import common_service

logger = get_logger("svc.kit")


# ── 조회 ───────────────────────────────────────────────────
def get_wait_list() -> dict:
    """발행 대기 목록. ready_yn 으로 발행 버튼 활성화 판단."""
    rows = query(kit_query.SELECT_KIT_WAIT_LIST)
    return {
        "kit_lists": rows,
        "total": len(rows),
        "ready_cnt": sum(1 for r in rows if r["ready_yn"]),
    }


def get_issued_list() -> dict:
    """태블릿 키팅 작업 목록. 발행된 건만."""
    rows = query(kit_query.SELECT_KIT_ISSUED_LIST)
    return {"kit_lists": rows, "total": len(rows)}


def get_kit_items(kit_seq: int) -> list[dict]:
    """키팅 1건에 담긴 자재 목록."""
    return query(kit_query.SELECT_KIT_ITEMS, (kit_seq,))


def get_verify_log(kit_seq: int) -> list[dict]:
    """3중 검증 이력. 오조립 클레임 시 증빙용."""
    return query(kit_query.SELECT_VERIFY_LOG, (kit_seq,))


# ── 발행 ───────────────────────────────────────────────────
def _check_ready(cur, kit_seq: int) -> dict:
    """발행 가능 여부 판정.

    '둘 다 있냐' 가 아니라 '필요한 게 다 됐냐'.
    W_LPN_SEQ 가 NULL 이면 세척 자재가 없는 공정이므로 기다리지 않는다.
    """
    cur.execute(kit_query.SELECT_KIT_STATE, (kit_seq,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"존재하지 않는 키팅입니다: {kit_seq}")

    (seq, order_no, proc_code, engine_no, engine_seq, status, hold_yn,
     life, w_seq, d_seq, w_status, w_loc, w_code,
     d_status, d_loc, d_code) = row

    if life != "ACTIVE":
        raise ValueError("취소된 키팅입니다")
    if hold_yn:
        raise ValueError("보류 중인 키팅입니다")
    if status == "ISSUED":
        raise ValueError("이미 발행된 키팅입니다")
    if status not in ("WAIT", "PICKING"):
        raise ValueError(f"발행할 수 없는 상태입니다 ({status})")

    if w_seq is None and d_seq is None:
        raise ValueError("W/D-LPN 이 발행되지 않았습니다")

    # 피킹 완료 여부
    cur.execute(kit_query.COUNT_PICK_NOT_PICKED, (kit_seq,))
    not_picked = cur.fetchone()[0]
    if not_picked > 0:
        raise ValueError(f"미완료 피킹 {not_picked}건이 남아 있습니다")

    # 세척 자재가 있는 공정만 세척 완료를 확인
    if w_seq is not None and w_status != "WASH_COMP":
        raise ValueError(f"세척이 완료되지 않았습니다 (W-LPN: {w_status})")

    # 비세척 자재가 있는 공정만 버퍼 적치를 확인
    if d_seq is not None and d_loc is None:
        raise ValueError("비세척 자재가 버퍼에 적치되지 않았습니다")

    return {
        "kit_seq": seq, "order_no": order_no, "proc_code": proc_code,
        "engine_no": engine_no, "engine_seq_no": engine_seq,
        "w_lpn_code": w_code, "d_lpn_code": d_code,
    }


def issue_kit(kit_seq: int, worker_id: str | None = None) -> dict:
    """키팅 지시 발행. WAIT → ISSUED."""
    with transaction() as cur:
        info = _check_ready(cur, kit_seq)

        cur.execute(kit_query.ISSUE_KIT, (kit_seq,))

        common_service.log_status(cur, "kit_table", kit_seq, "ISSUED",
                                  from_status="WAIT", worker_id=worker_id)

    logger.info("키팅 발행 - kit=%s %s/%s by=%s",
                kit_seq, info["engine_no"], info["proc_code"], worker_id)

    return {**info, "status": "ISSUED"}


def cancel_issue(kit_seq: int, worker_id: str | None = None) -> dict:
    """발행 취소. 키팅 착수 전에만 가능."""
    with transaction() as cur:
        cur.execute(kit_query.CANCEL_ISSUE_KIT, (kit_seq,))
        if cur.rowcount == 0:
            raise ValueError("발행 상태가 아니거나 이미 키팅이 진행되었습니다")

        common_service.log_status(cur, "kit_table", kit_seq, "WAIT",
                                  from_status="ISSUED", worker_id=worker_id,
                                  remark="발행 취소")

    logger.info("키팅 발행 취소 - kit=%s by=%s", kit_seq, worker_id)
    return {"kit_seq": kit_seq, "status": "WAIT"}


# ── 3중 검증 ───────────────────────────────────────────────
def verify_kit(kit_seq: int, lpn_code: str,
               device_id: str | None = None,
               worker_id: str | None = None) -> dict:
    """바코드 3중 검증. 키팅 스테이션에서 W/D-LPN 스캔 시 호출.

      ① 서열/호기 : 스캔 용기의 바인딩이 현재 지시와 일치하는가
      ② 공정(OP)  : 용기의 공정코드가 지시 공정과 일치하는가
      ③ 재고 상태 : W = WASH_COMP / D = 버퍼 적치 완료

    PASS/FAIL 무관하게 전 건 로그를 남긴다.
    오조립 클레임 시 투입 이력 증빙이 필요하기 때문.
    필요한 용기가 전부 PASS 되면 K-LPN 을 자동 생성한다.

    K-LPN 생성까지가 한 트랜잭션이고, 스테이션 배정(ACS 호출)은 그 밖에서
    따로 한다. ACS 를 트랜잭션 안에서 부르면 응답을 기다리는 5초 동안
    DB 락을 잡고, 무응답이면 롤백되면서 검증 로그까지 같이 날아간다.
    """
    code = lpn_code.strip().upper()

    with transaction() as cur:
        cur.execute(kit_query.SELECT_KIT_STATE, (kit_seq,))
        kit = cur.fetchone()
        if kit is None:
            raise ValueError(f"존재하지 않는 키팅입니다: {kit_seq}")

        (_, order_no, proc_code, engine_no, engine_seq, status, hold_yn,
         life, w_seq, d_seq, *_) = kit

        if life != "ACTIVE":
            raise ValueError("취소된 키팅입니다")
        if hold_yn:
            raise ValueError("보류 중인 키팅입니다")
        if status == "KITTED":
            raise ValueError("이미 키팅이 완료되었습니다")
        if status not in ("ISSUED", "KITTING"):
            raise ValueError(f"검증할 수 없는 상태입니다 ({status})")

        cur.execute(kit_query.SELECT_SCAN_LPN, (code,))
        lpn = cur.fetchone()
        if lpn is None:
            _log_verify(cur, kit_seq, None, code, 0, 0, 0,
                        "등록되지 않은 LPN", device_id, worker_id)
            raise ValueError(f"등록되지 않은 LPN 입니다: {code}")

        (lpn_seq, _, lpn_type, pstat, lstat,
         loc_seq, lpn_kit_seq, _, s_engine, s_proc, s_seq_no) = lpn

        # ① 서열/호기 검증
        ok_seq = (lpn_kit_seq == kit_seq
                  and s_engine == engine_no
                  and s_seq_no == engine_seq)

        # ② 공정(OP) 검증
        ok_proc = (s_proc == proc_code)

        # ③ 재고 상태 검증
        if lpn_type == "W":
            ok_stat = (pstat == "WASH_COMP")
        elif lpn_type == "D":
            ok_stat = (pstat == "PICK_COMP" and loc_seq is not None)
        else:
            ok_stat = False

        if lstat != "ACTIVE":
            ok_stat = False

        reasons = []
        if not ok_seq:
            reasons.append(f"서열/호기 불일치 (지시 {engine_no}/{engine_seq}"
                           f" ≠ 스캔 {s_engine}/{s_seq_no})")
        if not ok_proc:
            reasons.append(f"공정 불일치 (지시 {proc_code} ≠ 스캔 {s_proc})")
        if not ok_stat:
            reasons.append(f"용기 상태 부적합 ({lpn_type}-LPN: {pstat})")

        fail_reason = " / ".join(reasons) if reasons else None
        passed = not reasons

        _log_verify(cur, kit_seq, lpn_seq, code,
                    ok_seq, ok_proc, ok_stat,
                    fail_reason, device_id, worker_id)

        # 첫 PASS 가 곧 키팅 착수
        if passed and status == "ISSUED":
            cur.execute(kit_query.START_KITTING, (kit_seq,))
            common_service.log_status(cur, "kit_table", kit_seq, "KITTING",
                                      from_status="ISSUED",
                                      worker_id=worker_id, device_id=device_id,
                                      remark=f"3중 검증 착수 ({code})")

        # 필요한 용기가 전부 통과했는가
        need = sum(1 for x in (w_seq, d_seq) if x is not None)
        cur.execute(kit_query.COUNT_VERIFY_PASS, (kit_seq, kit_seq, kit_seq))
        done = cur.fetchone()[0]

        # 전량 통과 시 K-LPN 자동 생성
        k_info = None
        if passed and done >= need:
            k_info = _create_k_lpn(cur, kit_seq, order_no, engine_no,
                                   proc_code, engine_seq, w_seq, d_seq,
                                   device_id, worker_id)

    logger.info("3중 검증 %s - kit=%s lpn=%s (%s/%s) by=%s",
                "PASS" if passed else "FAIL", kit_seq, code, done, need, worker_id)

    # 스테이션 배정은 여기서 하지 않는다.
    #   ACS 소켓 프로세스가 KIT_COMP + station NULL 인 건을 생성순으로
    #   주워서 station_req 를 보내고, 응답을 받아 ISSUED 로 올린다.
    #   여기서 동기로 기다리면 ACS 가 죽어 있을 때 발행 버튼이 그대로 멈춘다.
    return {
        "kit_seq":      kit_seq,
        "lpn_code":     code,
        "lpn_type":     lpn_type,
        "result":       "PASS" if passed else "FAIL",
        "verify_seq":   bool(ok_seq),
        "verify_proc":  bool(ok_proc),
        "verify_stat":  bool(ok_stat),
        "fail_reason":  fail_reason,
        "verified_cnt": done,
        "need_cnt":     need,
        "k_lpn":        k_info,
    }


def _log_verify(cur, kit_seq, lpn_seq, code,
                ok_seq, ok_proc, ok_stat, reason, device_id, worker_id) -> int:
    """검증 로그 기록. FAIL 도 반드시 남긴다."""
    result = "PASS" if (ok_seq and ok_proc and ok_stat) else "FAIL"
    cur.execute(kit_query.INSERT_VERIFY_LOG,
                (kit_seq, lpn_seq, code,
                 int(bool(ok_seq)), int(bool(ok_proc)), int(bool(ok_stat)),
                 result, reason, device_id, worker_id))
    return cur.fetchone()[0]


# ── K-LPN 생성 ─────────────────────────────────────────────
def _create_k_lpn(cur, kit_seq, order_no, engine_no, proc_code, engine_seq,
                  w_seq, d_seq, device_id, worker_id) -> dict:
    """K-LPN 생성. 이미 열린 트랜잭션 커서를 받는다.

    W/D-LPN 의 자재를 K-LPN 하나로 합치고 원본은 소멸시킨다.
    원본 수량을 비우지 않으면 재고가 이중 계상된다.
    이후 AMR 은 K-LPN 만 추적한다.
    """
    cur.execute(kit_query.SELECT_KIT_DETAIL, (w_seq, d_seq))
    items = cur.fetchall()
    if not items:
        raise ValueError("담긴 자재가 없습니다")

    k_code = common_service.make_lpn_code(cur, "K")
    cur.execute(kit_query.INSERT_K_LPN,
                (k_code, kit_seq, order_no, engine_no, proc_code, engine_seq))
    k_seq = cur.fetchone()[0]

    for item_seq, qty in items:
        cur.execute(kit_query.INSERT_K_DETAIL, (k_seq, item_seq, qty, qty))

    for src in (w_seq, d_seq):
        if src is None:
            continue
        cur.execute(kit_query.INSERT_TXN_MERGE, (k_seq, device_id, worker_id, src))
        cur.execute(kit_query.CLEAR_SRC_DETAIL, (src,))
        cur.execute(kit_query.CONSUME_SRC_LPN, (src,))

    cur.execute(kit_query.UPDATE_KIT_DONE, (k_seq, kit_seq))
    common_service.log_status(cur, "kit_table", kit_seq, "KITTED",
                              from_status="KITTING", worker_id=worker_id,
                              remark=f"K-LPN {k_code}")

    logger.info("K-LPN 생성 - %s (kit=%s, 자재 %s종) by=%s",
                k_code, kit_seq, len(items), worker_id)

    return {"k_lpn_seq": k_seq, "k_lpn_code": k_code, "item_cnt": len(items)}
