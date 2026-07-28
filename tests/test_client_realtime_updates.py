from shared.model.board import Board
from shared.model.piece import Piece
from shared.model.position import Position
from client.main import apply_server_update_to_board, land_motion_on_board, ClientRealTimeArbiter


def test_apply_server_update_starts_motion_without_moving_piece_yet():
    # הכלי לא אמור "לקפוץ" ליעד מיד עם קבלת המהלך - רק להתחיל להנפיש אליו.
    # זה מה שמאפשר לכלי יריב שיושב על משבצת היעד להישאר גלוי עד רגע הנחיתה בפועל.
    board = Board(8, 8)
    board.grid[(0, 0)] = Piece("wP1", "P", "w", Position(0, 0))

    payload = {
        "state": {
            "last_move": {
                "from": [0, 0],
                "to": [0, 1],
            }
        }
    }

    arbiter = ClientRealTimeArbiter()
    apply_server_update_to_board(board, payload, arbiter)

    assert board.get_piece_at(Position(0, 0)) is not None
    assert board.get_piece_at(Position(0, 1)) is None
    assert len(arbiter.active_motions) == 1


def test_piece_lands_and_captures_only_when_motion_finishes():
    board = Board(8, 8)
    attacker = Piece("wP1", "P", "w", Position(0, 0))
    defender = Piece("bP1", "P", "b", Position(0, 1))
    board.grid[(0, 0)] = attacker
    board.grid[(0, 1)] = defender

    payload = {
        "state": {
            "last_move": {
                "from": [0, 0],
                "to": [0, 1],
            }
        }
    }

    arbiter = ClientRealTimeArbiter()
    apply_server_update_to_board(board, payload, arbiter)

    # באמצע האנימציה - הכלי הנאכל עדיין אמור להיות על הלוח
    arbiter.advance_visual_time(500)
    assert board.get_piece_at(Position(0, 1)) is defender

    # רק כשהתנועה מסתיימת בפועל, הכלי הנאכל נעלם והתוקף "נוחת" על היעד
    finished_motions = arbiter.advance_visual_time(600)
    for motion in finished_motions:
        land_motion_on_board(board, motion)

    assert board.get_piece_at(Position(0, 0)) is None
    assert board.get_piece_at(Position(0, 1)) is attacker


def test_rejected_arrival_reverts_optimistic_prediction():
    # אם השרת מדווח במפורש שמהלך נדחה ברגע ההגעה (הלוח השתנה תוך כדי התנועה),
    # הלקוח חייב לוותר על הניחוש האופטימי שלו ולחזור למצב שהשרת מאשר - לא להישאר
    # תקוע לצמיתות עם כלי שנראה כאילו זז בהצלחה כשבפועל הוא מעולם לא זז אצל השרת.
    board = Board(8, 8)
    board.grid[(0, 0)] = Piece("wP1", "P", "w", Position(0, 0))

    move_payload = {"state": {"last_move": {"from": [0, 0], "to": [0, 1]}}}
    arbiter = ClientRealTimeArbiter()
    apply_server_update_to_board(board, move_payload, arbiter)
    assert arbiter.pending_arrivals == {(0, 1): (0, 0)}

    tick_payload = {
        "board": {"0,0": {"piece_type": "P", "color": "w"}},
        "reverted_moves": [{"position": [0, 0]}],
    }
    apply_server_update_to_board(board, tick_payload, arbiter)

    assert arbiter.pending_arrivals == {}
    assert arbiter.active_motions == []
    assert board.get_piece_at(Position(0, 1)) is None
    assert board.get_piece_at(Position(0, 0)) is not None
