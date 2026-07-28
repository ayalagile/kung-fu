import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from bus.events import MatchFoundEvent
from bus.listeners.match_listener import on_match_found
from server.handlers import handle_play_msg, handle_login_msg, handle_create_room_msg
from server.logic.room_manager import room_manager
from server.state import server_state
from server.engine_adapter import EngineAdapter
from shared.model.board import Board
from shared.model.piece import Piece
from shared.model.position import Position
from shared.rules.rule_engine import RuleEngine
from shared.real_time.real_time_arbiter import RealTimeArbiter
from logic.engine.game_engine import GameEngine


class TestServerFlow(unittest.TestCase):
    def setUp(self):
        server_state.connected_clients.clear()

    async def _run(self, coro):
        return await coro

    def test_login_then_play_returns_ack(self):
        async def run_test():
            client_id = "client1"
            server_state.connected_clients[client_id] = {"websocket": AsyncMock(), "rating": 1200, "username": None}
            response_type, payload = await handle_play_msg(client_id, {}, AsyncMock())
            self.assertEqual(response_type, "play_ack")
            self.assertEqual(payload["status"], "queued")

        asyncio.run(run_test())

    def test_create_room_returns_room_id(self):
        async def run_test():
            client_id = "client1"
            server_state.connected_clients[client_id] = {"websocket": AsyncMock(), "rating": 1200, "username": None}
            response_type, payload = await handle_create_room_msg(client_id, {}, AsyncMock())
            self.assertTrue(payload["room_id"])
            self.assertEqual(response_type, "room_created")

        asyncio.run(run_test())

    def test_match_listener_uses_server_state_clients(self):
        async def run_test():
            client1_ws = AsyncMock()
            client2_ws = AsyncMock()
            server_state.connected_clients["client1"] = {"websocket": client1_ws, "rating": 1200, "username": None}
            server_state.connected_clients["client2"] = {"websocket": client2_ws, "rating": 1200, "username": None}

            await on_match_found(MatchFoundEvent(room_id="room-1", player1_id="client1", player2_id="client2"))

            self.assertEqual(client1_ws.send_text.await_count, 1)
            self.assertEqual(client2_ws.send_text.await_count, 1)

        asyncio.run(run_test())

    def test_broadcast_to_room_sends_to_username_alias(self):
        async def run_test():
            ws = AsyncMock()
            server_state.connected_clients["client1"] = {"websocket": ws, "rating": 1200, "username": "player1"}
            room = room_manager.rooms.get("room-test")
            if room is None:
                room = type("Room", (), {})()
                room.room_id = "room-test"
                room.players = ["client1"]
                room.viewers = []
                room_manager.rooms["room-test"] = room

            await room_manager.broadcast_to_room("room-test", {"type": "game_state_update"})

            self.assertEqual(ws.send_text.await_count, 1)

        asyncio.run(run_test())

    def test_engine_adapter_uses_real_board_and_rules(self):
        adapter = EngineAdapter()
        initial_state = adapter.get_initial_state()

        self.assertTrue(hasattr(initial_state["board"], "get_piece_at"))
        self.assertIsNotNone(initial_state["board"].get_piece_at(Position(0, 6)))

        valid, updated_state, error = adapter.validate_and_apply_move(
            initial_state,
            {"from": [0, 6], "to": [0, 5]}
        )

        self.assertTrue(valid, error)
        self.assertIsNone(updated_state["board"].get_piece_at(Position(0, 6)))
        self.assertIsNotNone(updated_state["board"].get_piece_at(Position(0, 5)))
        self.assertEqual(updated_state["turn"], "b")

    def test_airborne_defender_captures_arriving_attacker(self):
        # קפיצה היא הגנה: כלי שנמצא באוויר (קפיצה) בדיוק על משבצת היעד ברגע ההגעה
        # שורד ולוכד את הכלי שניסה לנחות עליו - הוא לא זה שנלכד.
        board = Board(8, 8)
        defender = Piece("bR1", "R", "b", Position(0, 0))
        attacker = Piece("wR1", "R", "w", Position(0, 1))
        board.grid[(0, 0)] = defender
        board.grid[(0, 1)] = attacker

        engine = GameEngine(board, RuleEngine(), RealTimeArbiter())

        self.assertTrue(engine.handle_jump_command((0, 0)))
        self.assertTrue(engine.handle_move_command((0, 1), (0, 0)))

        events = engine.handle_wait_command(1000)  # משך התנועה של משבצת אחת

        self.assertIsNone(board.get_piece_at(Position(0, 1)))
        self.assertIs(board.get_piece_at(Position(0, 0)), defender)
        self.assertEqual(attacker.state, "Captured")

        airborne_events = [e for e in events if e.get("event") == "airborne_capture"]
        self.assertEqual(len(airborne_events), 1)
        self.assertIs(airborne_events[0]["capturer"], defender)
        self.assertIs(airborne_events[0]["captured"], attacker)
        self.assertEqual(airborne_events[0]["from_pos"], Position(0, 1))


if __name__ == "__main__":
    unittest.main()
