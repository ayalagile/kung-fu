import json
import time
from bus.event_bus import event_bus
from bus.events import MatchFoundEvent
from server.state import server_state

async def on_match_found(event: MatchFoundEvent):
    match_msg = {
        "type": "match_found",
        "payload": {
            "room_id": event.room_id,
            "player1_id": event.player1_id,
            "player2_id": event.player2_id
        },
        "ts": int(time.time())
    }

    for client_id in [event.player1_id, event.player2_id]:
        client_data = server_state.connected_clients.get(client_id)
        if client_data:
            await client_data["websocket"].send_text(json.dumps(match_msg))

# רישום המאזין ל-Event Bus
event_bus.subscribe(MatchFoundEvent, on_match_found)