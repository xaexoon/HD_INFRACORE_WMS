from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.routers import input_router, pick_router, rack_router, history_router
from src.routers.master import item_master_router, rack_master_router, pick_master_router
from src.db.connection import init_db
from src.logger.logger import get_logger

import os
import sys

import uvicorn


# exe 실행 시 → exe 가 있는 폴더
# 일반 실행 시 → 프로젝트 루트
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WEB_BUILD_DIR = os.path.join(BASE_DIR, "web_build")


def create_app(origins: list = None, serve_static: bool = True) -> FastAPI:
    # 디버그 로그 (모듈 최상단에 있으면 spawn 시 두 번 찍혀서 함수 안으로 이동)
    print(f"[web_server] BASE_DIR: {BASE_DIR}")
    print(f"[web_server] WEB_BUILD_DIR: {WEB_BUILD_DIR}")
    print(f"[web_server] web_build 존재 여부: {os.path.exists(WEB_BUILD_DIR)}")

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    app.include_router(rack_master_router.router)
    app.include_router(item_master_router.router)
    app.include_router(pick_master_router.router)
    app.include_router(input_router.router)
    app.include_router(pick_router.router)
    app.include_router(rack_router.router)
    app.include_router(history_router.router)

    if serve_static and os.path.exists(WEB_BUILD_DIR):
        app.mount(
            "/static",
            StaticFiles(directory=os.path.join(WEB_BUILD_DIR, "static")),
            name="static",
        )

        @app.get("/{full_path:path}")
        async def serve_react(full_path: str):
            if full_path.startswith("api/"):
                # 200 dict 반환 → 진짜 404로 수정 (프론트가 성공으로 착각하지 않게)
                raise HTTPException(status_code=404, detail="Not Found")

            file_path = os.path.join(WEB_BUILD_DIR, full_path)
            if full_path and os.path.isfile(file_path):
                return FileResponse(file_path)

            return FileResponse(os.path.join(WEB_BUILD_DIR, "index.html"))

    return app


# ─────────────────────────────────────────────
# 추가된 부분: main.py가 프로세스로 실행하는 진입점
# ─────────────────────────────────────────────
def run_web(db_conf: dict, web_conf: dict | None = None):
    # 1) main에서 넘겨받은 접속정보로 DB 초기화 (실패 시 여기서 죽음)
    init_db(
        address=db_conf["address"],
        database=db_conf["database"],
        user=db_conf["user"],
        password=db_conf["password"],
    )

    # 2) 바인딩 주소/포트는 option.ini 값을 사용 (미지정 시 기존 동작 유지)
    web_conf = web_conf or {}
    host = web_conf.get("host", "0.0.0.0")
    port = web_conf.get("port", 8000)

    logger = get_logger("web")  # 모듈 최상단에 두면 spawn 시 중복 초기화됨
    app = create_app()
    logger.info(f"웹 서버 기동 (host={host}, port={port})")
    uvicorn.run(app, host=host, port=port)


# 단독 실행 (프로젝트 루트에서): python -m src.web_server
#   from src.routers ... 형태로 임포트하므로 프로젝트 루트가 sys.path 에 있어야 한다.
#   python src/web_server.py 로 직접 실행하면 ModuleNotFoundError 가 난다.
if __name__ == "__main__":
    from src.common.config_loader import load_config

    opt = load_config()
    run_web(
        db_conf={
            "address": opt.get("db_address", "127.0.0.1"),
            "database": opt.get("db_database"),
            "user": opt.get("db_user"),
            "password": opt.get("db_password"),
        },
        web_conf={
            "host": opt.get("web_server_host", "0.0.0.0"),
            "port": opt.getint("web_server_port", fallback=8000),
        },
    )