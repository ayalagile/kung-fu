from shared.model.board import Board
from shared.model.game_state import GameState
from shared.model.position import Position
from shared.rules.rule_engine import RuleEngine
from shared.real_time.real_time_arbiter import RealTimeArbiter
class GameEngine:
    def __init__(self, board: Board, rule_engine: RuleEngine, realtime_arbiter: RealTimeArbiter):
        self.board = board
        self.rule_engine = rule_engine
        self.arbiter = realtime_arbiter
        self.game_state = GameState()

    def handle_jump_command(self, pos: tuple) -> bool:
        """פקודה חדשה להפעלת קפיצה לכלי במיקום מסוים"""
        if self.game_state.is_game_over:
            return False

        position = Position(pos[0], pos[1])
        piece = self.board.get_piece_at(position)
        if not piece:
            return False

        # הפעלת הקפיצה דרך ה-Arbiter
        return self.arbiter.start_jump(piece)

    def handle_move_command(self, from_pos: tuple, to_pos: tuple) -> bool:
        if self.game_state.is_game_over:
            return False

        from_position = Position(from_pos[0], from_pos[1])
        to_position = Position(to_pos[0], to_pos[1])

        piece = self.board.get_piece_at(from_position)
        if not piece:
            return False

        # חוק: מניעת תנועה של כלי שנע כרגע או כלי שנמצא כרגע באמצע קפיצה (Airborne)
        if hasattr(piece, 'state') and piece.state in ["Moving", "Jumping"]:
            return False
            
        if self.arbiter.is_piece_airborne(piece):
            return False

        if not self.rule_engine.validate_requested_move(piece, to_position, self.board):
            return False

        success = self.arbiter.start_motion(piece, from_position, to_position)
        return success

    def handle_wait_command(self, duration_ms: int) -> list:
        if self.game_state.is_game_over:
            return []
        events = self.arbiter.advance_simulated_time(duration_ms, self)
        return events

    def resolve_arrival(self, motion) -> dict:
        piece = motion.piece
        to_pos = motion.to_pos
        from_pos = motion.from_pos

        if not self.rule_engine.validate_requested_move(piece, to_pos, self.board):
            piece.state = "Idle"
            return {"event": "invalid_on_arrival", "piece": piece, "pos": from_pos}

        target_piece = self.board.get_piece_at(to_pos)
        event_data = {"event": "move_completed", "piece": piece, "from": from_pos, "to": to_pos}

        if target_piece:
            event_data["captured"] = target_piece
            target_piece.state = "Captured"
            if str(target_piece.type).upper() == 'K':
                event_data["event"] = "king_captured"
                self.game_state.trigger_game_over(winner_color=piece.color)

        self.board.move_piece(from_pos, to_pos)
        
        if hasattr(piece, 'position'):
            piece.position = to_pos
        print(f"DEBUG Arrival: piece_type={piece.type} ({type(piece.type)}), color={piece.color} ({type(piece.color)}), to_y={to_pos.y}")
        if str(piece.type).upper() == 'P':
            is_promotion_row = (str(piece.color).lower() == 'w' and to_pos.y == 0) or \
                               (str(piece.color).lower() == 'b' and to_pos.y == self.board.height - 1)
            if is_promotion_row:
                piece.type = 'Q'
                event_data["promoted"] = True

        if target_piece and hasattr(self.arbiter, 'cancel_all_for_piece'):
            self.arbiter.cancel_all_for_piece(target_piece)

        return event_data