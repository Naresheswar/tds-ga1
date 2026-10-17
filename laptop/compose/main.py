import os
import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
r = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), port=6379, decode_responses=True)


@app.post("/hit/{key}")
def hit(key: str):
    return {"key": key, "count": int(r.incr(f"hits:{key}"))}


@app.get("/count/{key}")
def count(key: str):
    return {"key": key, "count": int(r.get(f"hits:{key}") or 0)}


@app.get("/healthz")
def healthz():
    try:
        ok = r.ping()
    except Exception:
        ok = False
    return {"status": "ok" if ok else "error", "redis": "up" if ok else "down"}
