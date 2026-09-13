# -*- coding: utf-8 -*-
"""src/common/engine_model.py — 엔진 모델별 라인 구분 설정

ERP 지시가 들어오면 ORDER_H.KMATN(모델)으로 라인을 판정한다.
모델은 자주 바뀌지 않으므로 테이블 대신 ini 로 관리한다.
"""
import os
import sys
import configparser

from src.logger.logger import get_logger

logger = get_logger("svc")

_conf: configparser.ConfigParser | None = None


def _base_dir() -> str:
    """exe 실행 시 exe 폴더, 일반 실행 시 프로젝트 루트."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load() -> configparser.ConfigParser:
    """설정 파일을 한 번만 읽어 캐시한다."""
    global _conf
    if _conf is not None:
        return _conf

    path = os.path.join(_base_dir(), "engine_model.ini")
    cp = configparser.ConfigParser()
    cp.optionxform = str            # 키 대소문자 보존

    if not os.path.exists(path):
        logger.error("엔진 모델 설정 파일 없음: %s", path)
    else:
        cp.read(path, encoding="utf-8")
        models = [s for s in cp.sections()]
        logger.info("엔진 모델 설정 로드 - %s개 (%s)", len(models), ", ".join(models))

    _conf = cp
    return _conf


def reload() -> None:
    """파일을 다시 읽는다. 모델 추가 후 재시작 없이 반영할 때."""
    global _conf
    _conf = None
    _load()


def get_model(model: str) -> dict:
    """모델 설정 조회.

    설정에 없고 strict = true 면 예외를 던진다.
    방산 모델이 설정에서 누락되면 대차 없이 발행되어
    조용히 잘못 흐르는 것을 막기 위함이다.
    """
    cp = _load()
    name = (model or "").strip()

    if name not in cp.sections():
        d = cp["DEFAULT"] if cp.defaults() else {}
        strict = str(d.get("strict", "true")).lower() == "true"
        if strict:
            raise ValueError(f"engine_model.ini 에 등록되지 않은 모델입니다: {name}")

        logger.warning("설정에 없는 모델 — 기본값으로 처리: %s", name)
        return {
            "model":      name,
            "line_type":  d.get("line_type", "LARGE"),
            "line_name":  d.get("line_name", name),
            "auto_proc":  False,
            "cart_yn":    False,
            "bs_yn":      False,
            "sloc":       None,
            "arbpl_pre":  None,
            "proc_digit": True,
            "registered": False,
        }

    s = cp[name]
    return {
        "model":      name,
        "line_type":  s.get("line_type", "LARGE"),
        "line_name":  s.get("line_name", name),
        "auto_proc":  s.getboolean("auto_proc", fallback=False),
        "cart_yn":    s.getboolean("cart_yn", fallback=False),
        "bs_yn":      s.getboolean("bs_yn", fallback=False),
        "sloc":       s.get("sloc", None),
        "arbpl_pre":  s.get("arbpl_pre", None),
        "proc_digit": s.getboolean("proc_digit", fallback=True),
        "registered": True,
    }


def get_model_safe(model: str) -> dict:
    """예외 없이 모델 설정을 돌려준다.

    조회 화면용. strict 여부와 무관하게 항상 dict 를 반환하고
    설정에 없으면 registered = False 로 표시한다.
    가공 경로에서는 get_model() 을 그대로 써서 미등록을 막는다.
    """
    name = (model or "").strip()
    try:
        return get_model(name)
    except ValueError:
        cp = _load()
        d = cp["DEFAULT"] if cp.defaults() else {}
        return {
            "model":      name,
            "line_type":  d.get("line_type", "LARGE"),
            "line_name":  "미등록 모델",
            "auto_proc":  False,
            "cart_yn":    False,
            "bs_yn":      False,
            "sloc":       None,
            "arbpl_pre":  None,
            "proc_digit": True,
            "registered": False,
        }


def get_all() -> list[dict]:
    """등록된 모델 전체. 화면 셀렉트박스용."""
    return [get_model(s) for s in _load().sections()]


def is_defense(model: str) -> bool:
    """방산 라인 여부. 대차 단위 발행이 필요한지 판단한다."""
    return get_model(model)["line_type"] == "DEFENSE"