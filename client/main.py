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
from shared.model.piece import Piece
from shared.model.position import Position
from shared.real_time.real_time_arbiter import RealTimeArbiter

raw_click_pixels = None

class ClientRealTimeArbiter(RealTimeArbiter):
    # מרחיב את ה-Arbiter המשותף בהנהלת חשבונות שרלוונטית ללקוח בלבד: מעקב אחרי מהלכים
    # שהאנימציה החזותית שלהם הסתיימה מקומית אך עוד לא אושרו על ידי הלוח הסמכותי של השרת.
    # לא שייך למחלקה המשותפת (server/client) כי לשרת - שהוא מקור האמת - אין בכלל צורך בזה.
    def __init__(self):
        super().__init__()
        self.pending_arrivals = {}  # {to_pos_tuple: from_pos_tuple}

def setup_initial_board_pieces(game_board: Board):
    game_board.grid[(0, 0)] = Piece("bR1", "R", "b", Position(0, 0))
    game_board.grid[(1, 0)] = Piece("bN1", "N", "b", Position(1, 0))
    game_board.grid[(2, 0)] = Piece("bB1", "B", "b", Position(2, 0))
    game_board.grid[(3, 0)] = Piece("bQ", "Q", "b", Position(3, 0))
    game_board.grid[(4, 0)] = Piece("bK", "K", "b", Position(4, 0))
    game_board.grid[(5, 0)] = Piece("bB2", "B", "b", Position(5, 0))
    game_board.grid[(6, 0)] = Piece("bN2", "N", "b", Position(6, 0))
    game_board.grid[(7, 0)] = Piece("bR2", "R", "b", Position(7, 0))

    for i in range(8):
        game_board.grid[(i, 1)] = Piece(f"bP{i+1}", "P", "b", Position(i, 1))

    game_board.grid[(0, 7)] = Piece("wR1", "R", "w", Position(0, 7))
    game_board.grid[(1, 7)] = Piece("wN1", "N", "w", Position(1, 7))
    game_board.grid[(2, 7)] = Piece("wB1", "B", "w", Position(2, 7))
    game_board.grid[(3, 7)] = Piece("wQ", "Q", "w", Position(3, 7))
    game_board.grid[(4, 7)] = Piece("wK", "K", "w", Position(4, 7))
    game_board.grid[(5, 7)] = Piece("wB2", "B", "w", Position(5, 7))
    game_board.grid[(6, 7)] = Piece("wN2", "N", "w", Position(6, 7))
    game_board.grid[(7, 7)] = Piece("wR2", "R", "w", Position(7, 7))

    for i in range(8):
        game_board.grid[(i, 6)] = Piece(f"wP{i+1}", "P", "w", Position(i, 6))

def reconcile_board_with_server(board: Board, board_dict: dict, arbiter=None):
    # מיישר את הלוח המקומי במלואו מול הלוח הסמכותי שהשרת שלח: מוסיף כלים חסרים,
    # מסיר כלים שנעלמו (למשל נלכדו), ומעדכן type/color (למשל הכתרה לחייל שהגיע לשורה האחרונה).
    # רלוונטי רק להודעות tick טהורות - בהודעת move/jump מיידית הלוח שהשרת שולח עדיין
    # לא משקף את ההגעה בפועל (זו מתרחשת מאוחר יותר ב-resolve_arrival), אז שם סומכים
    # אך ורק על from/to לצורך תנועה אופטימית מקומית.
    if board_dict is None:
        return

    server_pieces = {}
    for key, info in board_dict.items():
        try:
            x_str, y_str = key.split(",")
            server_pieces[(int(x_str), int(y_str))] = info
        except (ValueError, AttributeError):
            continue

    # משבצות שמוחרגות מהיישור: תנועה מקומית שעדיין מונפשת, ותנועות שהאנימציה
    # שלהן כבר הסתיימה חזותית אך הלוח הסמכותי טרם אישר שהכלי אכן עזב את המקור
    # (resolve_arrival בשרת מתרחש רק כשה-Tick שם מסיים, לא בהכרח בו-זמנית ללקוח) -
    # אחרת נקבל רגע קצר שבו הכלי "קופץ" בחזרה למקור ואז שוב ליעד.
    protected_positions = set()
    if arbiter is not None:
        for motion in arbiter.active_motions:
            protected_positions.add(motion.from_pos.to_tuple())
            protected_positions.add(motion.to_pos.to_tuple())

        confirmed_arrivals = []
        for to_tuple, from_tuple in arbiter.pending_arrivals.items():
            if from_tuple in server_pieces:
                protected_positions.add(to_tuple)
                protected_positions.add(from_tuple)
            else:
                confirmed_arrivals.append(to_tuple)
        for to_tuple in confirmed_arrivals:
            del arbiter.pending_arrivals[to_tuple]

    # הסרת כלים שכבר לא קיימים בלוח הסמכותי (נלכדו וכו')
    for pos_tuple, piece in list(board.grid.items()):
        if pos_tuple in protected_positions:
            continue
        if piece is not None and pos_tuple not in server_pieces:
            board.grid[pos_tuple] = None

    # עדכון כלים קיימים / הוספת כלים חסרים לפי הלוח הסמכותי
    for pos_tuple, info in server_pieces.items():
        if pos_tuple in protected_positions:
            continue
        piece_type = info.get("piece_type", "")
        color = info.get("color", "")
        piece = board.grid.get(pos_tuple)
        if piece is not None:
            piece.type = piece_type
            piece.color = color
        else:
            board.grid[pos_tuple] = Piece(
                f"{color}{piece_type}{pos_tuple[0]}{pos_tuple[1]}", piece_type, color, Position(*pos_tuple)
            )

def apply_server_update_to_board(board: Board, payload: dict, arbiter=None):
    # קפיצה: מיקום יחיד [x, y] - הכלי לא מחליף משבצת, רק עולה לאוויר לצורך האנימציה/מנגנון ההגנה
    last_jump = payload.get("last_jump")
    if isinstance(last_jump, (list, tuple)) and len(last_jump) == 2:
        jump_piece = board.get_piece_at(Position(last_jump[0], last_jump[1]))
        if jump_piece is not None and arbiter is not None:
            arbiter.start_jump(jump_piece)
        return

    last_move = payload.get("state", {}).get("last_move") or payload.get("move")

    if not isinstance(last_move, dict):
        # אין מהלך/קפיצה חדשים בהודעה הזו - זהו עדכון tick טהור, והלוח שהתקבל כבר סופי.
        # מהלכים שהשרת דיווח עליהם במפורש כ"התהפכו" - נפסלו ברגע ההגעה, או שכלי אויב
        # שהיה באוויר (קפיצה) לכד את הכלי המגיע במקום להילכד ממנו - חייבים לבטל את ההגנה
        # על המשבצות שלהם עכשיו. אחרת ה"המתנה לאישור" הייתה נמשכת לנצח (המקור אצל השרת
        # אף פעם לא מתפנה כרגיל במקרים האלה), וה-reconcile למטה לעולם לא היה מתקן את
        # הניחוש האופטימי השגוי של הלקוח.
        if arbiter is not None:
            reverted_positions = {
                tuple(item["position"]) for item in payload.get("reverted_moves", [])
                if isinstance(item, dict) and item.get("position")
            }
            for to_tuple, from_tuple in list(arbiter.pending_arrivals.items()):
                if from_tuple in reverted_positions:
                    del arbiter.pending_arrivals[to_tuple]
            # אם המהלך התהפך בזמן שהאנימציה עדיין רצה מקומית - אין טעם לתת לה להמשיך
            # להנפיש לעבר יעד שהשרת כבר קבע שלא יתקבל, מבטלים אותה כאן ומיד.
            for motion in list(arbiter.active_motions):
                if motion.from_pos.to_tuple() in reverted_positions:
                    arbiter.active_motions.remove(motion)
                    motion.piece.state = "Idle"

        reconcile_board_with_server(board, payload.get("board"), arbiter)
        return

    from_pos = last_move.get("from")
    to_pos = last_move.get("to")
    if not from_pos or not to_pos:
        return

    from_position = Position(from_pos[0], from_pos[1])
    to_position = Position(to_pos[0], to_pos[1])

    piece = board.get_piece_at(from_position)
    if piece is None:
        # אולי הכלי כבר זז או שהמיקום ממופה אחרת, ננסה לחפש לפי עמדה אם צריך
        return

    if arbiter is not None:
        # לא מזיזים בלוח כאן בכוונה: הכלי שעל משבצת היעד (אם יש) צריך להישאר גלוי
        # ולהיאכל רק ברגע שהכלי הנע *מגיע* אליו בפועל (land_motion_on_board), לא ברגע השליחה.
        arbiter.cancel_motion_for_piece(piece)
        arbiter.start_motion(piece, from_position, to_position)
        piece.state = "Moving"
        arbiter.pending_arrivals[to_position.to_tuple()] = from_position.to_tuple()
    else:
        # בלי Arbiter אין מי "שינחית" את הכלי בסיום אנימציה - מבצעים את התנועה מיידית
        board.grid[from_position.to_tuple()] = None
        board.grid[to_position.to_tuple()] = piece
        piece.position = to_position

def land_motion_on_board(board: Board, motion):
    # קורה בדיוק ברגע שהאנימציה של הכלי הנע מסתיימת חזותית: רק עכשיו הכלי "נוחת" בפועל
    # על משבצת היעד - וכל כלי שהיה שם (הכלי הנאכל) נעלם בדיוק ברגע הזה, לא לפני.
    from_tuple = motion.from_pos.to_tuple()
    to_tuple = motion.to_pos.to_tuple()
    if board.grid.get(from_tuple) is motion.piece:
        board.grid[from_tuple] = None
    captured_piece = board.grid.get(to_tuple)
    if captured_piece is not None and captured_piece is not motion.piece:
        # אותה מוסכמה כמו בשרת (resolve_arrival): כלי שנאכל מסומן Captured, לא רק מוסר.
        captured_piece.state = "Captured"
    board.grid[to_tuple] = motion.piece
    motion.piece.position = motion.to_pos
def mouse_callback(event, x, y, flags, param):
    global raw_click_pixels
    if event == cv2.EVENT_LBUTTONDOWN:
        raw_click_pixels = (x, y)

async def message_listener(client: NetworkClient, current_board: Board, realtime_arbiter=None):
    try:
        async for raw_message in client.listen():
            try:
                msg = json.loads(raw_message)
                print(f"<- קיבל מהשרת: {msg}") # <--- הוספת הדפסה כדי לראות מה השרת חושב
                msg_type, payload = msg.get("type"), msg.get("payload", {})

                if msg_type == "match_found":
                    print(f"נמצאה התאמה! נכנסת לחדר: {payload.get('room_id')}")
                elif msg_type == "game_state_update":
                    apply_server_update_to_board(current_board, payload, realtime_arbiter)
                elif msg_type in ("error", "move_error", "jump_error"):
                    print(f"שגיאת שרת: {payload.get('message')}")
            except json.JSONDecodeError:
                pass
    except asyncio.CancelledError:
        pass

async def run_client(mode: str, extra_arg: str = None, username: str = None):
    global raw_click_pixels

    client = NetworkClient(uri="ws://localhost:8001/ws")
    await client.connect()

    user_to_login = username if username else ("player1" if mode == "play" else f"player_{mode}")

    print(f"--- התחברות בתור ({user_to_login}) ---")
    await client.send_message("login", {"username": user_to_login, "password": "mypassword123"}, f"req_login_{user_to_login}")
    await asyncio.sleep(0.5)

    if mode == "play":
        await client.send_message("play", {}, "req_play")
    elif mode == "create":
        await client.send_message("create_room", {}, "req_create")
    elif mode == "join" and extra_arg:
        await client.send_message("join_room", {"room_id": extra_arg}, "req_join")

    # אתחול הלוח והכלים הראשוניים
    game_board = Board(8, 8)
    setup_initial_board_pieces(game_board)
    
    realtime_arbiter = ClientRealTimeArbiter()
    controller = Controller(board_mapper=BoardMapper(square_size=CELL_SIZE), network_client=client)
    renderer = Renderer(arbiter=realtime_arbiter, sprite_manager=SpriteManager(assets_base_path="assets/pieces_mine"))

    window_name = f"Chess Game - {user_to_login}"
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, mouse_callback)

    listener_task = asyncio.create_task(message_listener(client, game_board, realtime_arbiter))
    print(f"הלקוח מחובר ורץ מול השרת! לחץ 'q' ליציאה.")

    last_time = time.time()
    try:
        while True:
            current_time = time.time()
            dt_ms = int((current_time - last_time) * 1000)
            last_time = current_time

            if dt_ms > 0:
                renderer.sprite_manager.update_time(dt_ms)
                finished_motions = realtime_arbiter.advance_visual_time(dt_ms)
                for motion in finished_motions:
                    land_motion_on_board(game_board, motion)

            if raw_click_pixels is not None:
                px, py = raw_click_pixels
                raw_click_pixels = None
                controller.handle_click(px - renderer.start_x, py - renderer.start_y)

            cv2.imshow(window_name, renderer.render(game_board, selected_pos=controller.selected_pos).img)
            
            if (cv2.waitKey(1) & 0xFF == ord('q')) or (cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1):
                break

            await asyncio.sleep(0.016)
    finally:
        listener_task.cancel()
        await client.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "play"
    asyncio.run(run_client(action, sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3] if len(sys.argv) > 3 else None))