import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from database import init_db
from router import router


app = FastAPI(title="Retail Autopsy Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    init_db()
    from scanner import fetch_and_store_liquidations

    await fetch_and_store_liquidations()
    scheduler.add_job(fetch_and_store_liquidations, "interval", minutes=30)
    scheduler.start()
    port = os.getenv("PORT", "8000")
    print(f"Retail Autopsy Engine started. Dashboard: http://localhost:{port}")


@app.on_event("shutdown")
async def shutdown_event():
    if scheduler.running:
        scheduler.shutdown()


app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
