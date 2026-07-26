import json
import asyncio
import time
from fastapi import WebSocket
from bus.event_bus import event_bus
from bus.events import ClientDisconnectedEvent, PlayerQueuedEvent
from server.auth import handle_login, handle_register
from server.logic.matchmaking import matchmaking_system
from server.logic.room_manager import room_manager
from server.state import server_state

disconnect_timers = {}

async def handle_register_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    response_payload = await handle_register(payload)
    return "register_result", response_payload

async def handle_login_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    global client_id_ref  # לטיפול בעדכון מזהה הלקוח מול connected_clients אם נדרש
    response_payload = await handle_login(payload)
    
    if response_payload.get("success"):
        user_info = response_payload.get("user", {})
        username = user_info.get("username")
        user_rating = user_info.get("rating", 1200)

        if username and client_id in server_state.connected_clients:
            client_data = server_state.connected_clients.pop(client_id)
            client_data["rating"] = user_rating
            client_data["username"] = username
            server_state.connected_clients[username] = client_data
            
    return "login_result", response_payload

async def handle_play_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    client_info = server_state.connected_clients.get(client_id)
    player_rating = client_info.get("rating", 1200) if isinstance(client_info, dict) else 1200

    await event_bus.publish(PlayerQueuedEvent(
        client_id=client_id, 
        rating=player_rating
    ))
    return "play_ack", {"status": "queued", "message": "Searching for match..."}

async def handle_room_menu_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    return "room_menu_ack", {"status": "ok", "action": "room_menu", "message": "Room menu requested"}

async def handle_create_room_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    room_id = await room_manager.create_room(client_id)
    return "room_created", {"status": "ok", "room_id": room_id, "role": "player", "player_number": 1}

async def handle_join_room_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    target_room_id = payload.get("room_id", "")
    result = await room_manager.join_room(client_id, target_room_id)
    return "join_room_result", result

async def handle_cancel_room_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    result = await room_manager.cancel_room(client_id)
    return "cancel_room_result", result

async def handle_join_queue_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    room_id = matchmaking_system.add_to_queue(client_id)
    if room_id:
        players = matchmaking_system.active_rooms.get(room_id, [])
        for p_id in players:
            if p_id in server_state.connected_clients:
                match_msg = {
                    "type": "match_found",
                    "payload": {"room_id": room_id, "opponent_id": [p for p in players if p != p_id][0]},
                    "ts": int(time.time())
                }
                await server_state.connected_clients[p_id]["websocket"].send_text(json.dumps(match_msg))
        return "queue_result", {"status": "matched", "room_id": room_id}
    else:
        return "queue_result", {"status": "queued", "message": "Waiting for an opponent..."}

async def handle_leave_queue_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    matchmaking_system.remove_from_queue(client_id)
    return "queue_result", {"status": "left_queue"}

async def handle_move_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    move_data = payload.get("move", {})
    session = room_manager.get_session_by_client(client_id)
    
    if not session:
        await websocket.send_json({
            "type": "error",
            "payload": {"message": "You are not in an active game session."},
            "ts": int(time.time())
        })
        return "", {}

    success, result = await session.handle_move(client_id, move_data)
    
    if not success:
        await websocket.send_json({
            "type": "move_error",
            "payload": {"message": result},
            "ts": int(time.time())
        })
        return "", {}
    else:
        broadcast_message = {
            "type": "game_state_update",
            "payload": {
                "room_id": session.room_id,
                "last_move": move_data,
                "state": result
            },
            "ts": int(time.time())
        }
        await room_manager.broadcast_to_room(session.room_id, broadcast_message)
        return "", {}
async def handle_jump_msg(client_id: str, payload: dict, websocket: WebSocket) -> tuple[str, dict]:
    jump_data = payload.get("position", [])
    session = room_manager.get_session_by_client(client_id)
    
    if not session:
        await websocket.send_json({
            "type": "error",
            "payload": {"message": "You are not in an active game session."},
            "ts": int(time.time())
        })
        return "", {}

    # קריאה לפונקציית הקפיצה במנוע המשחק/סשן של השרת
    success, result = await session.handle_jump(client_id, jump_data)
    
    if not success:
        await websocket.send_json({
            "type": "jump_error",
            "payload": {"message": result},
            "ts": int(time.time())
        })
        return "", {}
    else:
        broadcast_message = {
            "type": "game_state_update",
            "payload": {
                "room_id": session.room_id,
                "last_jump": jump_data,
                "state": result
            },
            "ts": int(time.time())
        }
        await room_manager.broadcast_to_room(session.room_id, broadcast_message)
        return "", {}

async def handle_player_disconnect(event: ClientDisconnectedEvent):
    client_id = event.client_id
    
    # 1. בדקי אם השחקן נמצא כרגע בחדר משחק פעיל
    room = room_manager.get_session_by_client(client_id)
    if not room:
        return

    # 2. הגדירו פונקציית טיימר שתרוץ לאחר 20 שניות אם השחקן לא יחזור
    async def resign_if_not_returned():
        try:
            await asyncio.sleep(20)
            
            # בדיקה האם השחקן עדיין מנותק ולא חזר לחדר
            current_room = room_manager.get_session_by_client(client_id)
            if current_room and client_id in current_room.players:
                # הסרת השחקן מהחדר והכרזת הפסד/ניצחון ליריב
                current_room.remove_participant(client_id)
                
                win_msg = {
                    "type": "opponent_disconnected",
                    "payload": {"message": "Opponent disconnected. You win by default."},
                    "ts": int(time.time())
                }
                await room_manager.broadcast_to_room(current_room.room_id, win_msg)
                
        except asyncio.CancelledError:
            # השחקן התחבר מחדש בזמן, הטיימר בוטל בהצלחה
            pass
        finally:
            disconnect_timers.pop(client_id, None)

    # 3. הפעלת הטיימר ברקע
    timer_task = asyncio.create_task(resign_if_not_returned())
    disconnect_timers[client_id] = timer_task
disconnect_timers = {}

event_bus.subscribe(ClientDisconnectedEvent, handle_player_disconnect)
MESSAGE_HANDLERS= {
    "register": handle_register_msg,
    "login": handle_login_msg,
    "play": handle_play_msg,
    "room_menu": handle_room_menu_msg,
    "create_room": handle_create_room_msg,
    "join_room": handle_join_room_msg,
    "cancel_room": handle_cancel_room_msg,
    "join_queue": handle_join_queue_msg,
    "leave_queue": handle_leave_queue_msg,
    "move": handle_move_msg,
    "jump": handle_jump_msg,
}