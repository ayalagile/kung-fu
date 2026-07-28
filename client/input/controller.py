import asyncio
from client.input.board_mapper import BoardMapper
from client.network.network_client import NetworkClient
from shared.model.position import Position

class Controller:
    def __init__(self, board_mapper: BoardMapper, network_client: NetworkClient, board_size: int = 8):
        self.board_mapper = board_mapper
        self.network_client = network_client
        self.board_size = board_size
        self.selected_pos = None  # ישמור טאפל של (x, y) עבור המיקום שנבחר

    def handle_click(self, pixel_x: int, pixel_y: int):
        # 1. תרגום הפיקסלים למיקום לוגי בעזרת המפר
        current_pos = self.board_mapper.map_pixels_to_cell(pixel_x, pixel_y)
        cx, cy = current_pos

        # התעלמות מלחיצות מחוץ ללוח (למשל על הרקע סביבו)
        if not (0 <= cx < self.board_size and 0 <= cy < self.board_size):
            return

        # --- זיהוי הקפיצה בתוך הקונטרולר ---
        if self.selected_pos == current_pos:
            from_pos = self.selected_pos
            self.selected_pos = None  # איפוס הבחירה
            asyncio.create_task(
                self.network_client.send_message(
                    msg_type="jump",
                    payload={"position": [from_pos[0], from_pos[1]]}
                )
            )
            return
        # ------------------------------------------

        # מקרה א': אין בחירה קודמת - שמירת המיקום הנוכחי
        if self.selected_pos is None:
            self.selected_pos = current_pos
            return

        # מקרה ב' או ג': יש בחירה קודמת ולחצו על משבצת אחרת -> שליחת המהלך לשרת!
        from_pos = self.selected_pos
        self.selected_pos = None  # איפוס הבחירה לקראת הלחיצה הבאה
        
        asyncio.create_task(
            self.network_client.send_message(
                msg_type="move",
                payload={
                    "move": {
                        "from": [from_pos[0], from_pos[1]],
                        "to": [cx, cy]
                    }
                }
            )
        )