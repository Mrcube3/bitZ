import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import init_db, get_db
from router import router

app = FastAPI(title="Retail Autopsy Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

init_db()
with get_db() as db:
    count = db.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0]
if count == 0:
    from scanner import SYMBOLS, _simulate_events
    import database as db_module
    for symbol in SYMBOLS:
        for event in _simulate_events(symbol, 300):
            db_module.insert_liquidation(event)

frontend_dir = os.path.join(ROOT, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

from mangum import Mangum
handler = Mangum(app, lifespan="off")
