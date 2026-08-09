# src/common/config_loader.py
import os
import sys
import configparser

def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        # exe로 빌드된 경우: 실행 파일이 있는 폴더
        return os.path.dirname(sys.executable)
    # 개발 환경: common → src → 프로젝트 루트 (두 단계 위로)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_config(filename: str = "option.ini", section: str = "option",
                logger=None) -> configparser.SectionProxy:
    def _log(level, msg):
        if logger:
            getattr(logger, level)(msg)
        else:
            print(msg)

    config_path = os.path.join(get_base_dir(), filename)
    _log("info", f"config 경로: {config_path}")
    if not os.path.exists(config_path):
        _log("error", f"설정 파일을 찾을 수 없습니다: {config_path}")
        raise FileNotFoundError(config_path)

    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    _log("info", f"읽은 섹션: {config.sections()}")
    return config[section]