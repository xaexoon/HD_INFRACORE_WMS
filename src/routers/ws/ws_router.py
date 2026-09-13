from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.services.ws import ws_service
from src.logger.logger import get_logger

router = APIRouter()
logger = get_logger("socket")


@router.websocket("/ws/rfid")
async def rfid_ws(ws: WebSocket):
    """핸디 RFID 앱 접속.

    접속하면 태그를 쓰지 않은 K-LPN 목록을 주기적으로 받는다.
    쓰기가 끝나면 RFID_DONE 을 회신해 목록에서 뺀다.
    """
    await ws.accept()
    n = await ws_service.register(ws)
    logger.info("핸디 접속 - 현재 %s대", n)

    try:
        while True:
            # 파싱은 서비스에 맡긴다. receive_json() 으로 받으면 깨진 전문이
            # 왔을 때 원문을 볼 기회도 없이 여기서 예외가 터진다.
            raw = await ws.receive_text()
            await ws_service.on_receive(ws, raw)
    except WebSocketDisconnect:
        n = await ws_service.unregister(ws)
        logger.info("핸디 해제 - 현재 %s대", n)
    except Exception:
        await ws_service.unregister(ws)
        logger.exception("핸디 오류")