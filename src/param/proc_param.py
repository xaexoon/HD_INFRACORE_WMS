# -*- coding: utf-8 -*-
"""src/common/proc_param.py — 공정별 목적지 매핑

  K-LPN 을 어느 투입 포트로 보낼지 정한다.
  공정이 늘면 해당 모델 딕셔너리에 한 줄 추가하고 서버를 재시작한다.

  ※ 매핑에 없는 공정은 K-LPN 발행이 차단된다.
    목적지를 모르는 키트를 만들면 AMR 이 갈 곳이 없기 때문.
"""
from src.logger.logger import get_logger

logger = get_logger("svc")


DX37 = {
    10:  "AH-0010",
    20:  "AH-0020",
    30:  "AH-0030",
    40:  "AH-0040",
    50:  "AH-0050",
    60:  "AH-0060",
    70:  "AH-0070",
    80:  "AH-0080",
    90:  "AH-0090",
    100: "AH-0100",
    110: "AH-0110",
    120: "AH-0120",
    130: "AH-0130",
    140: "AH-0140",
    150: "AH-0150",
}

EDX08   = {}
EDX_DEF = {}

# 모델명 → 매핑. engine_model.ini 의 섹션명과 같아야 한다.
DEST = {
    "EDX37":   DX37,
    "EDX08":   EDX08,
    "EDX_DEF": EDX_DEF,
}


def get_dest(model: str, proc_code) -> str | None:
    """공정의 목적지 코드. 없으면 None.

    proc_code 는 DB 에서 문자열로 오지만 매핑 키는 숫자라
    양쪽을 모두 시도한다.
    """
    m = (model or "").strip()
    procs = DEST.get(m)
    if procs is None:
        logger.warning("목적지 매핑에 없는 모델: %s", m)
        return None

    p = str(proc_code).strip()
    dest = procs.get(p)
    if dest is None and p.isdigit():
        dest = procs.get(int(p))

    if dest is None:
        logger.warning("목적지 매핑에 없는 공정: %s / %s", m, p)
    return dest


def missing_procs(model: str, proc_codes: list) -> list:
    """매핑이 빠진 공정 목록. 신규 모델 등록 후 누락 점검용."""
    return [p for p in proc_codes if get_dest(model, p) is None]