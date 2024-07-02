import uuid
import random
import json
import uvicorn
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from fastapi.responses import HTMLResponse

wordsPath = "words.json"

with open(wordsPath) as file:
    words = json.load(file)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Game:
    def __init__(self):
        self.players = {}
        self.hostPlayerId = None
        self.currentPlayerNumber = None
        self.currentPlayerId = None
        self.started = False
        self.levelStarted = False
        self.levelStartedAt = None
        self.currentWord = None

        self.levelScore = {}
        self.totalScore = {}

class Player:
    def __init__(self, name):
        self.id = str(uuid.uuid4())
        self.name = name
        self.connection = None
        
    def getDto(self):
        return PlayerDto(**self.__dict__)

class PlayerDto(BaseModel):
    id: str
    name: str


SETTINGS = {
    "levelDuration": 60,
    "guessSuccessReward": 1,
    "guessFailFee": 1
}
GAME = Game()

@app.get("/")
async def index():
    with open("index.html") as index:
        return HTMLResponse(content=index.read(), status_code=200)

@app.post("/register/{name}")
async def register(name: str):
    player = Player(name)
    GAME.players[player.id] = player
    
    return JSONResponse(player.getDto().dict())

@app.post("/join/{playerId}")
async def join(playerId: str):
    if playerId not in GAME.players:
        raise HTTPException(status_code=404, detail="Player not found")
        
    if GAME.started:
        raise HTTPException(status_code=403, detail="Game already started")
        
    if GAME.hostPlayerId is None:
        GAME.hostPlayerId = playerId
    
    await broadcastUpdateMessage()


@app.post("/start")
async def start():
    GAME.started = True
    GAME.currentPlayerNumber = 0
    GAME.currentPlayerId = list(GAME.players.keys())[0]
    
    for player in GAME.players.keys():
        GAME.totalScore[player] = 0
        GAME.levelScore[player] = 0
    
    await broadcastUpdateMessage()
    

@app.post("/start_level")
async def startLevel():
    GAME.currentWord = getNextWord()
    GAME.levelStarted = True
    GAME.levelStartedAt = datetime.now()    
    await broadcastUpdateMessage()
    

@app.post("/word_guessed") #this should be safe ideally
async def wordGuessed():
    await setWordResult(True)
    
    
@app.post("/word_not_guessed") #this should be safe ideally
async def wordNotGuessed():
    await setWordResult(False)


@app.post("/get_state/{playerId}")
async def getState(playerId: str):
    state = {
        "players": list(map(lambda player: player.getDto().dict(), GAME.players.values())),
        "started": GAME.started,
        "needsToBeStarted": not GAME.started and playerId == GAME.hostPlayerId,
        "levelStarted": GAME.levelStarted,
        "levelNeedsToBeStarted": not GAME.levelStarted and playerId == GAME.currentPlayerId,
        "word": GAME.currentWord if playerId == GAME.currentPlayerId else None,
        "levelScore": GAME.levelScore,
        "totalScore": GAME.totalScore
    }

    return JSONResponse(state)


@app.websocket("/ws/{playerId}")
async def websocket_endpoint(websocket: WebSocket, playerId: str):
    if playerId not in GAME.players:
        raise HTTPException(status_code=404, detail="Player not found")

    await websocket.accept()
    GAME.players[playerId].connection = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        GAME.players[playerId].connection = None


async def broadcastUpdateMessage():
    for player in GAME.players.values():
        if player.connection:
            message = { 'action': 'game state updated' }
            await player.connection.send_text(json.dumps(message))


async def setWordResult(result):
    scoreDelta = SETTINGS["guessSuccessReward"] if result else -SETTINGS["guessFailFee"]
    GAME.levelScore[GAME.currentPlayerId] += scoreDelta
    GAME.totalScore[GAME.currentPlayerId] += scoreDelta
    
    if (datetime.now() - GAME.levelStartedAt).seconds < SETTINGS["levelDuration"]:
        GAME.currentWord = getNextWord()
    else:
        GAME.currentWord = None
        GAME.levelStarted = False
        GAME.levelStartedAt = None
        GAME.currentPlayerNumber = (GAME.currentPlayerNumber + 1) % len(GAME.players)
        GAME.currentPlayerId = list(GAME.players.keys())[GAME.currentPlayerNumber]
        
        if GAME.currentPlayerNumber == 0:
            for player in GAME.players.keys():
                GAME.totalScore[player] = 0
        
    await broadcastUpdateMessage()
    
    
def getNextWord():
    return random.choice(words)

    
if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='Alies', description='Alies Game')
    parser.add_argument('ip')
    parser.add_argument('-p', '--port')
    args = parser.parse_args()
    uvicorn.run(app, host=args['ip'], port=args['port'])