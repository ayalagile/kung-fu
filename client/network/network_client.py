import asyncio
import json
import logging
import time
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ClientNetwork")

class NetworkClient:
    def __init__(self, uri: str = "ws://localhost:8001/ws"):
        self.uri = uri
        self.websocket = None

    async def connect(self):
        logger.info(f"Connecting to {self.uri}...")
        self.websocket = await websockets.connect(self.uri)
        logger.info("Connected successfully!")

    async def send_message(self, msg_type: str, payload: dict, request_id: str = None):
        if not self.websocket:
            raise RuntimeError("Not connected to server")

        envelope = {
            "type": msg_type,
            "payload": payload,
            "request_id": request_id or "req_1",
            "ts": int(time.time())
        }
        
        raw_data = json.dumps(envelope)
        logger.info(f"Sending: {raw_data}")
        await self.websocket.send(raw_data)

    async def listen(self):
        try:
            async for message in self.websocket:
                logger.info(f"Received from server: {message}")
                yield message
        except websockets.ConnectionClosed:
            logger.info("Connection closed by server")

    async def close(self):
        if self.websocket:
            await self.websocket.close()
            logger.info("Connection closed")