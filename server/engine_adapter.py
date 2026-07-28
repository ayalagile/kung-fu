from typing import Tuple, Dict, Any
from shared.model.board import Board
from shared.model.piece import Piece
from shared.model.position import Position
from shared.rules.rule_engine import RuleEngine
from shared.real_time.real_time_arbiter import RealTimeArbiter
from logic.engine.game_engine import GameEngine

class EngineAdapter:
    def __init__(self):
        self.board = Board(8, 8)
        self.rule_engine = RuleEngine()
        self.arbiter = RealTimeArbiter()
        self.game_engine = GameEngine(self.board, self.rule_engine, self.arbiter)
        
        # פריסת כלים ראשונית חיונית כדי שהמנוע יזהה את הכלים בלוח
        self._setup_initial_pieces()

    def _setup_initial_pieces(self):
        # שחור (שורות 0 ו-1)
        piece_types = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
        for i, pt in enumerate(piece_types):
            self.board.grid[(i, 0)] = Piece(f"b{pt}{i}", pt, "b", Position(i, 0))
        for i in range(8):
            self.board.grid[(i, 1)] = Piece(f"bP{i}", "P", "b", Position(i, 1))

        # לבן (שורות 6 ו-7)
        for i in range(8):
            self.board.grid[(i, 6)] = Piece(f"wP{i}", "P", "w", Position(i, 6))
        for i, pt in enumerate(piece_types):
            self.board.grid[(i, 7)] = Piece(f"w{pt}{i}", pt, "w", Position(i, 7))

    def get_initial_state(self) -> Dict[str, Any]:
        return {
            "board": self._board_to_dict(self.board),
            "turn": "player1",
            "status": "active"
        }

    def get_current_board(self) -> Dict[str, Dict[str, str]]:
        return self._board_to_dict(self.board)

    def _board_to_dict(self, board: Board) -> Dict[str, Dict[str, str]]:
        board_dict = {}
        for pos, piece in board.grid.items():
            if piece is not None:
                key = f"{pos[0]},{pos[1]}" if isinstance(pos, (tuple, list)) else str(pos)
                # במקום להחזיר כתובת זיכרון עם str(piece), נחזיר מילון נתונים נקי לכלי
                board_dict[key] = {
                    "piece_type": getattr(piece, "piece_type", getattr(piece, "type", "")),
                    "color": getattr(piece, "color", "")
                }
        return board_dict
    
    def validate_and_apply_move(self, current_state: Dict[str, Any], move_data: Dict[str, Any], player_color: str = None) -> Tuple[bool, Dict[str, Any], str]:
        try:
            if not move_data:
                return False, current_state, "Empty move received"

            from_data = move_data.get("from")
            to_data = move_data.get("to")

            if not from_data or not to_data:
                return False, current_state, "Invalid move coordinates"

            # המרה מפורשת ומוגנת למבנה טאפל (או Position) כדי למנוע היפוך שורות ועמודות
            if isinstance(from_data, dict):
                from_tuple = (from_data.get("y", from_data.get("row", 0)), from_data.get("x", from_data.get("col", 0)))
                to_tuple = (to_data.get("y", to_data.get("row", 0)), to_data.get("x", to_data.get("col", 0)))
            else:
                from_tuple = tuple(from_data)
                to_tuple = tuple(to_data)

            # הדפסת ה-Debug מתבצעת כעת *אחרי* שהמשתנים הוגדרו בהצלחה
            print(f"DEBUG MAPPING -> From: {from_tuple}, To: {to_tuple}")

            if player_color is not None:
                piece_at_source = self.board.get_piece_at(Position(from_tuple[0], from_tuple[1]))
                if piece_at_source is None:
                    return False, current_state, "No piece at source position"
                if str(piece_at_source.color).lower() != str(player_color).lower():
                    return False, current_state, "Cannot move opponent's piece"

            success = self.game_engine.handle_move_command(from_tuple, to_tuple)
            
            if not success:
                return False, current_state, "Move rejected by GameEngine / RealTimeArbiter"

            updated_state = current_state.copy()
            updated_state["board"] = self._board_to_dict(self.board)
            updated_state["last_move"] = move_data

            return True, updated_state, ""

        except Exception as e:
            return False, current_state, str(e)

    def validate_and_apply_jump(self, current_state: Dict[str, Any], jump_data: Any, player_color: str = None) -> Tuple[bool, Dict[str, Any], str]:
        try:
            if not jump_data:
                return False, current_state, "Invalid jump coordinates"

            # תמיכה במבנה רשימה או מילון עבור הקפיצה
            if isinstance(jump_data, dict):
                jump_tuple = (jump_data.get("y", jump_data.get("row", 0)), jump_data.get("x", jump_data.get("col", 0)))
            else:
                jump_tuple = tuple(jump_data)

            if player_color is not None:
                piece_at_source = self.board.get_piece_at(Position(jump_tuple[0], jump_tuple[1]))
                if piece_at_source is None:
                    return False, current_state, "No piece at jump position"
                if str(piece_at_source.color).lower() != str(player_color).lower():
                    return False, current_state, "Cannot jump opponent's piece"

            success = self.game_engine.handle_jump_command(jump_tuple)
            
            if not success:
                return False, current_state, "Jump rejected by GameEngine / RealTimeArbiter"

            updated_state = current_state.copy()
            # תיקון קריטי: מחזירים את הלוח המעודכן במקום null
            updated_state["board"] = self._board_to_dict(self.board)
            updated_state["last_jump"] = jump_data

            return True, updated_state, ""

        except Exception as e:
            return False, current_state, str(e)