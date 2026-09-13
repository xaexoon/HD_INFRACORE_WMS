# -*- coding: utf-8 -*-
"""K-LPN AMR 호출 상태.

    CREATED      K-LPN 생성          WMS
    CALLED       AMR 호출 성공       WMS
    CALL_FAILED  AMR 호출 실패       ACS
    ACCEPTED     AMR 배차 성공       ACS
    RUNNING      AMR 동작 중         ACS
    COMPLETED    공정 도착 완료      ACS
    CANCELED     취소                —

WMS 가 세우는 것(CREATED / CALLED)과 ACS 가 알려주는 것이 나뉜다.
ACS 가 WMS 소관 상태를 되돌리지 못하게 막는다. 그러지 않으면
호출이 끝난 건이 CREATED 로 되돌아가 다시 호출된다.
"""

from src.db.connection import transaction
from src.logger.logger import get_logger
from src.queries import kit_query
from src.services import common_service

logger = get_logger("svc.acsstat")


# WMS 가 직접 세우는 상태. ACS 가 보내오면 거부한다.
WMS_OWNED = {"CREATED", "CALLED"}

# ACS 가 알려줄 수 있는 상태.
ACS_OWNED = {"CALL_FAILED", "ACCEPTED", "RUNNING", "COMPLETED", "CANCELED"}

ALL_STATUS = WMS_OWNED | ACS_OWNED


def set_status(lpn_code: str, to_status: str,
               worker_id: str | None = None,
               remark: str | None = None) -> bool:
    """K-LPN 상태를 바꾸고 이력을 남긴다. 실제로 바뀌었는지 돌려준다.

    같은 상태가 다시 오면 False (이력이 중복으로 쌓이지 않는다).
    """
    with transaction() as cur:
        cur.execute(kit_query.SELECT_KLPN_SEQ, (lpn_code,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"없는 K-LPN 입니다: {lpn_code}")
        k_seq, from_status = row

        cur.execute(kit_query.UPDATE_KLPN_CALL_STATUS,
                    (to_status, lpn_code, to_status))
        if cur.rowcount == 0:
            return False        # 상태 그대로. 같은 값이 다시 온 것

        common_service.log_status(cur, "lpn_master", k_seq, to_status,
                                  from_status=from_status,
                                  worker_id=worker_id, remark=remark)

    logger.info("K-LPN 상태 - %s %s -> %s", lpn_code, from_status, to_status)
    return True


def update_call_status(lpn_code: str, status: str) -> bool:
    """[2-1] ACS 가 알려온 상태를 반영한다.

    모르는 값을 그대로 넣으면 그 K-LPN 이 어떤 조회에도 안 잡히는 상태로
    빠져 화면에서도 배치에서도 사라진다. 반드시 걸러낸다.
    """
    code = (lpn_code or "").strip()
    to_status = (status or "").strip().upper()

    if not code:
        raise ValueError("lpn_code 가 비어 있습니다")

    if to_status not in ALL_STATUS:
        raise ValueError(f"정의되지 않은 상태입니다: {status!r} "
                         f"(가능: {', '.join(sorted(ALL_STATUS))})")

    if to_status in WMS_OWNED:
        # ACS 가 CREATED 로 되돌리면 이미 호출한 건이 다시 호출된다.
        raise ValueError(f"WMS 가 관리하는 상태입니다: {to_status}")

    return set_status(code, to_status, remark="ACS 통보")
