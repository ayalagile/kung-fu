import asyncio
import websockets
import json

async def test_game_engine_integration():
    uri = "ws://localhost:8001/ws"
    
    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        # יצירת חדר והצטרפות של שחקן שני
       # יצירת חדר והמתנה להודעת האישור הנכונה
        await ws1.send(json.dumps({"type": "create_room", "payload": {}}))
        
        room_id = None
        while True:
            res1 = await ws1.recv()
            data1 = json.loads(res1)
            if data1.get("type") == "room_created":
                room_id = data1.get("payload", {}).get("room_id")
                break
        await ws2.send(json.dumps({"type": "join_room", "payload": {"room_id": room_id}}))
        await ws2.recv() # ניקוי הודעת הצטרפות
        
        # שליחת מהלך למנוע המשחק
        print("שליחת מהלך למנוע...")
        await ws1.send(json.dumps({
            "type": "move",
            "payload": {"move": {"from": [0, 0], "to": [0, 1]}} # דוגמה לפורמט מהלך
        }))
        # שליחת מהלך למנוע המשחק
        print("שליחת מהלך למנוע...")
        await ws1.send(json.dumps({
            "type": "move",
            "payload": {"move": {"from": [0, 0], "to": [0, 1]}}
        }))
        
        # המתנה והצגת הודעת עדכון מצב המשחק או שגיאת מהלך
        print("ממתין לתשובת מנוע המשחק...")
        while True:
            response = await asyncio.wait_for(ws1.recv(), timeout=3.0)
            data = json.loads(response)
            msg_type = data.get("type")
            
            # הדפסת הודעות רלוונטיות למשחק ודילוג על הודעות חיבור ישנות
            if msg_type in ["game_state_update", "move_error", "error"]:
                print("תגובת השרת לאחר מהלך:", data)
                break
            else:
                print(f"הודעת מערכת בדרך: {msg_type} (ממשיך להאזין...)")
        # האזנה לתשובה או לעדכון מצב הלוח
        

asyncio.run(test_game_engine_integration())