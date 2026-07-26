# import asyncio
# import sys
# from client.network.network_client import NetworkClient

# async def run_client(mode: str, extra_arg: str = None, username: str = None):
#     client = NetworkClient()
#     try:
#         await client.connect()
#         listen_task = asyncio.create_task(client.listen())

#         # קביעת שם המשתמש: לפי הפרמטר, או ברירת מחדל לפי המצב
#         user_to_login = username if username else ("player1" if mode == "play" else f"player_{mode}")

#         # 1. התחברות
#         print(f"--- Login ({user_to_login}) ---")
#         await client.send_message(
#             msg_type="login",
#             payload={"username": user_to_login, "password": "mypassword123"},
#             request_id=f"req_login_{user_to_login}"
#         )
#         await asyncio.sleep(1)

#         # 2. ביצוע הפעולה לפי המצב
#         if mode == "register":
#             print(f"\n--- Registering user {user_to_login}... ---")
#             await client.send_message(
#                 msg_type="register",
#                 payload={"username": user_to_login, "password": "mypassword123"},
#                 request_id=f"req_reg_{user_to_login}"
#             )
#         elif mode == "create":
#             print("\n--- Creating room... ---")
#             await client.send_message(
#                 msg_type="create_room",
#                 payload={},
#                 request_id="req_create"
#             )
#         elif mode == "join" and extra_arg:
#             print(f"\n--- Joining room {extra_arg}... ---")
#             await client.send_message(
#                 msg_type="join_room",
#                 payload={"room_id": extra_arg},
#                 request_id="req_join"
#             )
#         elif mode == "play":
#             print("\n--- Entering Matchmaking Queue... ---")
#             await client.send_message(
#                 msg_type="play",
#                 payload={},
#                 request_id="req_play"
#             )
#             print("DEBUG: Processing play message...")
#         else:
#             print("\nUnknown mode or missing parameters")

#         # המתנה לקבלת תשובות/אירועים מהשרת
#         await asyncio.sleep(30)
#         listen_task.cancel()
#     finally:
#         await client.close()

# if __name__ == "__main__":
#     action = sys.argv[1] if len(sys.argv) > 1 else "play"
#     arg = sys.argv[2] if len(sys.argv) > 2 else None
#     user = sys.argv[3] if len(sys.argv) > 3 else None
    
#     asyncio.run(run_client(action, arg, user))
import asyncio
import sys
import json
import cv2
import time
from client.network.network_client import NetworkClient
from client.input.board_mapper import BoardMapper
from client.input.controller import Controller
from client.ui.renderer import Renderer, CELL_SIZE
from client.ui.sprite_manager import SpriteManager
from shared.model.board import Board
from shared.real_time.real_time_arbiter import RealTimeArbiter

raw_click_pixels = None

def mouse_callback(event, x, y, flags, param):
    global raw_click_pixels
    if event == cv2.EVENT_LBUTTONDOWN:
        raw_click_pixels = (x, y)

async def message_listener(client: NetworkClient, current_board: Board):
    try:
        async for raw_message in await client.listen():
            try:
                msg = json.loads(raw_message)
                msg_type = msg.get("type")
                payload = msg.get("payload", {})

                if msg_type == "match_found":
                    room_id = payload.get("room_id")
                    print(f"נמצאה התאמה! נכנסת לחדר: {room_id}")
                
                elif msg_type == "game_state_update":
                    print("Received board update from server!")
                
                elif msg_type in ("error", "move_error", "jump_error"):
                    print(f"Server error: {payload.get('message')}")

            except json.JSONDecodeError:
                pass
    except asyncio.CancelledError:
        pass

async def run_client(mode: str, extra_arg: str = None, username: str = None):
    global raw_click_pixels

    client = NetworkClient(uri="ws://localhost:8001/ws")
    await client.connect()

    # קביעת שם המשתמש לפי הפרמטרים בשורת הפקודה
    user_to_login = username if username else ("player1" if mode == "play" else f"player_{mode}")

    # 1. התחברות
    print(f"--- Login ({user_to_login}) ---")
    await client.send_message(
        msg_type="login",
        payload={"username": user_to_login, "password": "mypassword123"},
        request_id=f"req_login_{user_to_login}"
    )
    await asyncio.sleep(0.5)

    # 2. פעולה ראשונית (כניסה לתור או יצירת חדר)
    if mode == "play":
        print("\n--- Entering Matchmaking Queue... ---")
        await client.send_message(
            msg_type="play",
            payload={},
            request_id="req_play"
        )
    elif mode == "create":
        print("\n--- Creating room... ---")
        await client.send_message(
            msg_type="create_room",
            payload={},
            request_id="req_create"
        )
    elif mode == "join" and extra_arg:
        print(f"\n--- Joining room {extra_arg}... ---")
        await client.send_message(
            msg_type="join_room",
            payload={"room_id": extra_arg},
            request_id="req_join"
        )

    # 3. אתחול רכיבי ה-UI והממשק
    game_board = Board(8, 8)
    realtime_arbiter = RealTimeArbiter()
    
    board_mapper = BoardMapper(square_size=CELL_SIZE)
    controller = Controller(board_mapper=board_mapper, network_client=client)

    sprite_manager = SpriteManager(assets_base_path="assets/pieces_mine")
    renderer = Renderer(arbiter=realtime_arbiter, sprite_manager=sprite_manager)

    window_name = f"Chess Game - {user_to_login}"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)

    listener_task = asyncio.create_task(message_listener(client, game_board))

    print(f"הלקוח {user_to_login} מחובר ורץ מול השרת! לחצי 'q' ליציאה.")

    try:
        while True:
            if raw_click_pixels is not None:
                pixel_x, pixel_y = raw_click_pixels
                raw_click_pixels = None
                corrected_x = pixel_x - renderer.start_x
                corrected_y = pixel_y - renderer.start_y
                controller.handle_click(corrected_x, corrected_y)

            frame_img = renderer.render(game_board, selected_pos=controller.selected_pos)
            cv2.imshow(window_name, frame_img.img)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except Exception:
                break

            await asyncio.sleep(0.016)

    finally:
        listener_task.cancel()
        await client.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "play"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    user = sys.argv[3] if len(sys.argv) > 3 else None
    
    asyncio.run(run_client(action, arg, user))