from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.routers import (input_router, pick_router, rack_router, history_router,
                         kit_router, acs_router, rfid_router)
from src.routers.master import item_master_router, rack_master_router, pick_master_router, proc_master_router
from src.routers.ws import ws_router
from src.services.ws import ws_service          # ★ 실제 ws_service.py 경로에 맞게 조정
from src.db.connection import init_db
from src.logger.logger import get_logger

import asyncio
import os
import sys
import time

import uvicorn


# exe 실행 시 → exe 가 있는 폴더
# 일반 실행 시 → 프로젝트 루트
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WEB_BUILD_DIR = os.path.join(BASE_DIR, "web_build")


# 로그를 남기지 않을 정적 자원 확장자.
# 리액트 빌드물(js/css/이미지)까지 남기면 화면 한 번 열 때 수십 줄이 쏟아져
# 정작 봐야 할 업무 호출이 묻힌다.
_STATIC_EXT = (".js", ".css", ".map", ".ico", ".png", ".jpg", ".jpeg",
               ".gif", ".svg", ".woff", ".woff2", ".ttf", ".webp")


def _is_static(path: str) -> bool:
    return path.startswith("/static/") or path.lower().endswith(_STATIC_EXT)


def _add_access_log(app: FastAPI) -> None:
    """HTTP 요청 한 건을 한 줄로 남긴다.

    프론트(웹)와 QR PC 를 구분하지 않고 둘 다 API 로 본다.
    구분이 필요해지면 QR PC 가 헤더를 하나 붙이게 하고 여기서 읽으면 된다.

    uvicorn 자체 access 로그는 run() 에서 끈다. 그쪽은 콘솔로만 나가고
    파일에 남지 않아서, 파일에 남는 이 미들웨어로 일원화한다.

    웹소켓(/ws/rfid)은 HTTP scope 가 아니라 이 미들웨어를 타지 않는다.
    접속/해제 로그는 ws_router 쪽에서 남긴다.
    """
    logger = get_logger("api.http")

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        if _is_static(request.url.path):
            return await call_next(request)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 여기서 삼키면 안 된다. 남기고 그대로 올려보낸다.
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception("%s %s 처리 중 예외 (%.0fms)",
                             request.method, request.url.path, elapsed_ms)
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        # 4xx/5xx 는 경고로 올려 눈에 띄게 한다
        level = logger.warning if response.status_code >= 400 else logger.info
        level("%s %s %s (%.0fms)",
              request.method, request.url.path, response.status_code, elapsed_ms)
        return response


def _build_lifespan(logger):
    """RFID 브로드캐스트 루프를 앱 수명주기에 묶는다.

    on_event("startup") 은 deprecated 라 lifespan 으로 간다.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(ws_service.broadcast_loop(),
                                   name="rfid_broadcast_loop")

        # asyncio.create_task 는 태스크가 예외로 죽어도 아무 데도 알리지 않는다.
        # 콜백을 달아두지 않으면 RFID 전송이 조용히 멈춘 채로 서버가 계속 돈다.
        def _on_done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("RFID broadcast_loop 비정상 종료", exc_info=exc)

        task.add_done_callback(_on_done)
        logger.info("RFID broadcast_loop 기동")

        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("RFID broadcast_loop 종료 중 예외")
            logger.info("RFID broadcast_loop 종료")

    return lifespan


def create_app(origins: list = None, serve_static: bool = True) -> FastAPI:
    # 디버그 로그 (모듈 최상단에 있으면 spawn 시 두 번 찍혀서 함수 안으로 이동)
    print(f"[web_server] BASE_DIR: {BASE_DIR}")
    print(f"[web_server] WEB_BUILD_DIR: {WEB_BUILD_DIR}")
    print(f"[web_server] web_build 존재 여부: {os.path.exists(WEB_BUILD_DIR)}")

    logger = get_logger("sys.web")

    app = FastAPI(lifespan=_build_lifespan(logger))

    _add_access_log(app)

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
    app.include_router(proc_master_router.router)
    app.include_router(input_router.router)
    app.include_router(pick_router.router)
    app.include_router(rack_router.router)
    app.include_router(kit_router.router)
    app.include_router(history_router.router)
    app.include_router(ws_router.router)
    app.include_router(acs_router.router)
    app.include_router(rfid_router.router)
    if serve_static and os.path.exists(WEB_BUILD_DIR):
        app.mount(
            "/static",
            StaticFiles(directory=os.path.join(WEB_BUILD_DIR, "static")),
            name="static",
        )

        # 이 캐치올은 HTTP scope 만 잡는다. /ws/rfid 웹소켓 핸드셰이크는
        # 라우팅 단계에서 scope 가 달라 여기로 내려오지 않는다.
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

    logger = get_logger("sys.web")  # 모듈 최상단에 두면 spawn 시 중복 초기화됨

    # Windows 기본 Proactor 루프는 클라이언트가 연결 도중 끊으면
    # WinError 64 를 예외로 던진다. 동작에는 지장이 없으나 로그가 시끄러워
    # Selector 방식으로 전환한다.
    # uvicorn.run 이 루프를 만들기 전에 정책을 바꿔야 하므로 create_app 보다 앞에 둔다.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    app = create_app()
    logger.info(f"웹 서버 기동 (host={host}, port={port})")

    # log_config=None : uvicorn 이 logging 설정을 갈아엎지 않게 한다.
    #   기본값이면 uvicorn 이 자기 핸들러를 propagate=False 로 달아버려
    #   기동/오류 로그가 콘솔로만 나가고 web.log 에 남지 않는다.
    # access_log=False : 위 미들웨어와 겹치므로 끈다.
    # workers 는 지정하지 않는다. 2 이상이면 프로세스마다 broadcast_loop 가
    #   따로 돌아 핸디에 중복 전송된다.
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)


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