import socketio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import random

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
socket_app = socketio.ASGIApp(sio, app)

# Раздаём статику (твои модели, карты, звуки)
app.mount("/static", StaticFiles(directory="."), name="static")

# Список доступных машин и карт (сервер должен знать о них)
CAR_IDS = ["bmwe92", "mustang", "nissan370", "silvia"]
MAP_IDS = ["nring", "mscrc"]

# Хранилище комнат
# rooms = { "room_id": { ... } }
rooms = {}
player_rooms = {} # { sid: room_id }

@app.get("/")
async def index():
    return FileResponse("index.html")

@sio.event
async def connect(sid, environ):
    print(f"Подключён: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Отключён: {sid}")
    if sid in player_rooms:
        room_id = player_rooms[sid]
        if room_id in rooms:
            room = rooms[room_id]
            if sid in room["players"]:
                del room["players"][sid]
            
            if not room["players"]:
                del rooms[room_id]
            else:
                if room["host"] == sid:
                    room["host"] = list(room["players"].keys())[0]
                await sio.emit('room_update', room, room=room_id)
        del player_rooms[sid]

@sio.event
async def create_room(sid, data):
    nick = data.get("nick", "Player")
    room_id = f"room_{random.randint(1000, 9999)}"
    
    rooms[room_id] = {
        "id": room_id,
        "host": sid,
        "state": "lobby", # lobby, racing, results
        "settings": {
            "max_players": 4,
            "is_private": False,
            "password": "",
            "map_id": "nring",
            "allowed_cars": CAR_IDS
        },
        "players": {
            sid: {
                "nick": nick, "carId": "bmwe92", "ping": random.randint(10, 50), "score": 0, "is_ready": False
            }
        },
        "chat": [],
        "queue": [], # Порядок заездов
        "current_turn": 0
    }
    player_rooms[sid] = room_id
    await sio.enter_room(sid, room_id)
    await sio.emit('room_update', rooms[room_id], to=sid)

@sio.event
async def join_room(sid, data):
    room_id = data.get("room_id")
    nick = data.get("nick", "Player")
    password = data.get("password", "")
    
    if room_id not in rooms:
        return await sio.emit('error_msg', 'Комната не найдена', to=sid)
    
    room = rooms[room_id]
    if len(room["players"]) >= room["settings"]["max_players"]:
        return await sio.emit('error_msg', 'Комната заполнена', to=sid)
    
    if room["settings"]["is_private"] and room["settings"]["password"] != password:
        return await sio.emit('error_msg', 'Неверный пароль', to=sid)
    
    room["players"][sid] = {
        "nick": nick, "carId": "bmwe92", "ping": random.randint(10, 50), "score": 0, "is_ready": False
    }
    player_rooms[sid] = room_id
    await sio.enter_room(sid, room_id)
    await sio.emit('room_update', room, room=room_id)

@sio.event
async def update_settings(sid, data):
    room_id = player_rooms.get(sid)
    if not room_id or room_id not in rooms: return
    room = rooms[room_id]
    
    if room["host"] != sid: return
    
    room["settings"].update(data)
    await sio.emit('room_update', room, room=room_id)

@sio.event
async def change_car(sid, carId):
    room_id = player_rooms.get(sid)
    if not room_id or room_id not in rooms: return
    rooms[room_id]["players"][sid]["carId"] = carId
    await sio.emit('room_update', rooms[room_id], room=room_id)

@sio.event
async def send_chat(sid, text):
    room_id = player_rooms.get(sid)
    if not room_id or room_id not in rooms: return
    room = rooms[room_id]
    nick = room["players"][sid]["nick"]
    room["chat"].append({"nick": nick, "text": text})
    if len(room["chat"]) > 50: room["chat"].pop(0)
    await sio.emit('chat_update', room["chat"], room=room_id)

@sio.event
async def start_race(sid):
    room_id = player_rooms.get(sid)
    if not room_id or room_id not in rooms: return
    room = rooms[room_id]
    
    if room["host"] != sid: return
    
    if len(room["players"]) < 2:
        return await sio.emit('error_msg', 'Нужно минимум 2 игрока', to=sid)
    
    # Перемешиваем порядок заездов
    player_sids = list(room["players"].keys())
    random.shuffle(player_sids)
    
    room["queue"] = player_sids
    room["current_turn"] = 0
    room["state"] = "racing"
    
    for p_sid in player_sids:
        room["players"][p_sid]["score"] = 0
    
    await sio.emit('race_started', room, room=room_id)

@sio.event
async def finish_run(sid, score):
    room_id = player_rooms.get(sid)
    if not room_id or room_id not in rooms: return
    room = rooms[room_id]
    
    if room["state"] != "racing": return
    
    room["players"][sid]["score"] = score
    room["current_turn"] += 1
    
    if room["current_turn"] >= len(room["queue"]):
        # Все проехали - результаты
        room["state"] = "results"
        await sio.emit('race_results', room, room=room_id)
    else:
        # Следующий игрок
        await sio.emit('next_turn', room, room=room_id)

@sio.event
async def vote_rematch(sid):
    room_id = player_rooms.get(sid)
    if not room_id or room_id not in rooms: return
    room = rooms[room_id]
    
    if room["state"] != "results": return
    
    # Просто перезапускаем
    if room["host"] == sid:
        await start_race(sid)
