import json, re, time, uuid, math
from collections import defaultdict, deque

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

EMAIL = "24f3002833@ds.study.iitm.ac.in"
router = APIRouter()
START = time.time()

# ---------- Q3 CORS-aware metrics API ----------
@router.get("/stats")
def stats(values: str = ""):
    nums = [int(x) for x in re.split(r"[,\s]+", values.strip()) if x.strip()]
    n = len(nums)
    return {"email": EMAIL, "count": n, "sum": sum(nums), "min": min(nums) if nums else None,
            "max": max(nums) if nums else None, "mean": (sum(nums) / n) if n else None}

# ---------- Q4 OAuth / OIDC verify ----------
PUBKEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2okOHspNjgA+2rTLbeuY
cxiP/hG8C6Sb9iwg3yiLAA4HCnpITcbWCSelbvbYGuc3EbNy4xFyf5Cbj5DHJMID
EkryOgyd2giIIIBOUBj8S63uGcnRpOBh9NFatfNwheKuzsPuVNldu6A9cNteNpXc
WyJjG2axVfmq7i6SuKr1JoWYG7xTTAvKPujSl4OtsQfO3h5NepzdfXpr28oNnzfW
ed+zclR6BcmNNo/WVfJ4xyCLSf0BCOgdTgW6PdaChd1l9VDetJZVEgC5tkyvXsfI
SI6iyrYbKR0NEBSqq4XkadEjsCs4F1RncsS4LlgniT7GlkL9Mce3b0wGLs9/7ZIX
dQIDAQAB
-----END PUBLIC KEY-----"""
ISS = "https://idp.exam.local"
AUD = "tds-bj7xcyt3.apps.exam.local"

@router.post("/verify")
async def verify(request: Request):
    try:
        body = await request.json()
        tok = body.get("token", "")
        c = jwt.decode(tok, PUBKEY, algorithms=["RS256"], audience=AUD, issuer=ISS,
                       options={"require": ["exp", "iss", "aud"]})
        return {"valid": True, "email": c.get("email"), "sub": c.get("sub"), "aud": c.get("aud")}
    except Exception:
        return JSONResponse({"valid": False}, status_code=401)

# ---------- Q7 analytics ----------
API_KEY = "ak_jav7mm506mqdsnjir0sihaal"

@router.post("/analytics")
async def analytics(request: Request):
    if request.headers.get("x-api-key") != API_KEY:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    ev = body.get("events", []) or []
    tot = defaultdict(float)
    rev = 0.0
    for e in ev:
        a = float(e.get("amount", 0) or 0)
        if a > 0:
            rev += a
            tot[e.get("user")] += a
    top = max(tot.items(), key=lambda kv: kv[1])[0] if tot else None
    return {"email": EMAIL, "total_events": len(ev), "unique_users": len({e.get("user") for e in ev}),
            "revenue": round(rev, 2), "top_user": top}

# ---------- Q8 observability ----------
COUNTER = {"n": 0}
LOGS = deque(maxlen=500)

def observe(request: Request, rid: str):
    COUNTER["n"] += 1
    LOGS.append({"level": "info", "ts": time.time(), "path": request.url.path, "request_id": rid,
                 "method": request.method})

@router.get("/obs/work")
def work(n: int = 1):
    s = 0
    for i in range(max(0, min(n, 100000))):
        s += i
    return {"email": EMAIL, "done": n}

@router.get("/obs/metrics")
def metrics():
    txt = ("# HELP http_requests_total Total HTTP requests.\n# TYPE http_requests_total counter\n"
           f"http_requests_total {COUNTER['n']}\n")
    return PlainTextResponse(txt, media_type="text/plain; version=0.0.4")

@router.get("/obs/healthz")
def healthz():
    return {"status": "ok", "uptime_s": round(time.time() - START, 3)}

@router.get("/obs/logs/tail")
def logs_tail(limit: int = 20):
    return list(LOGS)[-max(1, limit):]

# ---------- Q10 structured extraction ----------
class Invoice(BaseModel):
    vendor: str
    amount: float
    currency: str
    date: str

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

def _date(text):
    m = re.search(r"(?:due|payable|payment)[^\n]{0,40}?(\d{4}-\d{2}-\d{2})", text, re.I) or re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})", text)
    if m and m.group(2).lower()[:3] in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()[:3]]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if m and m.group(1).lower()[:3] in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()[:3]]:02d}-{int(m.group(2)):02d}"
    return ""

SYM = {"$": "USD", "€": "EUR", "£": "GBP"}

def _amount(text):
    pat = r"(?:(USD|EUR|GBP|[$€£])\s?([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s?(USD|EUR|GBP))"
    best = None
    for kw in [r"(?:total|amount|balance)\s*(?:due|payable)?", r"due", ""]:
        for m in re.finditer((kw + r"[^\n\d$€£]{0,30}" if kw else "") + pat, text, re.I):
            cur = (m.group(1) or m.group(4) or "").upper()
            val = m.group(2) or m.group(3)
            best = (float(val.replace(",", "")), SYM.get(cur, cur))
            break
        if best:
            break
    if not best:
        m = re.search(r"(USD|EUR|GBP)", text, re.I)
        n = re.search(r"([\d,]+\.\d{2})", text)
        best = (float(n.group(1).replace(",", "")) if n else 0.0, m.group(1).upper() if m else "USD")
    return best

def _vendor(text):
    for p in [r"(?:vendor|from|supplier|seller|billed by|issued by|company)\s*[:\-]\s*([^\n,;]+)",
              r"([A-Z][\w&.\-]*(?:[ \t]+[A-Z][\w&.\-]*)*[ \t]+(?:Industries|Ltd\.?|LLC|Inc\.?|GmbH|Corp\.?|Co\.)(?:[ \t]+(?:Ltd\.?|LLC|Inc\.?))?)"]:
        m = re.search(p, text, re.I if "vendor" in p else 0)
        if m:
            return m.group(1).strip().rstrip(".") + ("." if m.group(1).strip().endswith(".") else "")
    first = text.strip().split("\n")[0] if text.strip() else ""
    return first[:80]

@router.post("/extract", response_model=Invoice)
async def extract(request: Request):
    try:
        body = await request.json()
        text = str(body.get("text", "")) if isinstance(body, dict) else ""
    except Exception:
        text = ""
    if not text.strip():
        return JSONResponse({"detail": "text is required"}, status_code=422)
    amt, cur = _amount(text)
    return Invoice(vendor=_vendor(text), amount=amt, currency=cur or "USD", date=_date(text))

# ---------- Q11 idempotency + pagination + rate limit ----------
TOTAL = 45
IDEM = {}
NEXT_ID = {"n": 1000}

@router.post("/api/orders", status_code=201)
async def create_order(request: Request):
    key = request.headers.get("idempotency-key")
    if key and key in IDEM:
        return JSONResponse(IDEM[key], status_code=201)
    try:
        body = await request.json()
    except Exception:
        body = {}
    NEXT_ID["n"] += 1
    order = {"id": str(NEXT_ID["n"]), **(body if isinstance(body, dict) else {})}
    order["id"] = str(NEXT_ID["n"])
    if key:
        IDEM[key] = order
    return JSONResponse(order, status_code=201)

@router.get("/api/orders")
def list_orders(limit: int = 10, cursor: str = ""):
    start = int(cursor) if cursor.isdigit() else 0
    limit = max(1, limit)
    ids = list(range(start + 1, min(TOTAL, start + limit) + 1))
    nxt = str(ids[-1]) if ids and ids[-1] < TOTAL else None
    return {"items": [{"id": i, "amount": 100} for i in ids], "next_cursor": nxt}

# ---------- Q12 middleware /ping ----------
@router.get("/mw/ping")
def ping(request: Request):
    return {"email": EMAIL, "request_id": request.state.request_id}

# ---------- Q13 / Q14 static answers ----------
@router.get("/stream.json")
def stream_answer():
    return {"A": {"text": "Report job-5b79fb62: café\nReady ✓", "complete": True, "error": None},
            "B": {"text": "Partial job-5b79fb62", "complete": False, "error": None},
            "C": {"text": "Draft job-5b79fb62", "complete": False, "error": "model unloaded"}}

@router.get("/docker.json")
def docker_answer():
    return {"A": {"steps": ["L3", "L4", "L5"], "seconds": 35},
            "B": {"steps": ["L1", "L2", "L3", "L4", "L5"], "seconds": 97},
            "C": {"steps": [], "seconds": 0},
            "D": {"steps": [], "seconds": 0},
            "E": {"steps": ["L4", "L5"], "seconds": 35}}

# ---------- shared middleware: CORS by path, request id, timing, rate limits ----------
EXAM = "https://exam.sanand.workers.dev"
STRICT = {"/stats": {"https://dash-nh251l.example.com"},
          "/mw/": {"https://app-60f4bq.example.com", EXAM}}
BUCKETS = {"/mw/ping": 15, "/api/orders": 17}
HITS = defaultdict(deque)

def allowed_origins(path):
    for p, s in STRICT.items():
        if path.startswith(p):
            return s
    return None  # wildcard

async def middleware(request: Request, call_next):
    t0 = time.perf_counter()
    path = request.url.path
    origin = request.headers.get("origin")
    allow = allowed_origins(path)
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid

    def cors_headers():
        h = {}
        if origin and (allow is None or origin in allow):
            h["Access-Control-Allow-Origin"] = origin if allow is not None else "*"
            if allow is not None:
                h["Vary"] = "Origin"
            h["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            h["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers") or "*"
            h["Access-Control-Expose-Headers"] = "X-Request-ID, X-Process-Time, Retry-After, Mcp-Session-Id"
            h["Access-Control-Max-Age"] = "600"
        elif not origin and allow is None:
            h["Access-Control-Allow-Origin"] = "*"
        return h

    if request.method == "OPTIONS":
        h = cors_headers()
        h.update({"X-Request-ID": rid, "X-Process-Time": f"{time.perf_counter() - t0:.6f}"})
        status = 204 if (allow is None or (origin in allow)) else 400
        return PlainTextResponse("", status_code=status, headers=h)

    if path.startswith("/obs/"):
        observe(request, rid)

    for p, limit in BUCKETS.items():
        if path.startswith(p) and not (p == "/api/orders" and request.method == "POST"):
            cid = request.headers.get("x-client-id") or (request.client.host if request.client else "anon")
            q = HITS[(p, cid)]
            now = time.time()
            while q and now - q[0] > 10:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(10 - (now - q[0])) + 1)
                h = cors_headers()
                h.update({"Retry-After": str(retry), "X-Request-ID": rid,
                          "X-Process-Time": f"{time.perf_counter() - t0:.6f}"})
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers=h)
            q.append(now)

    resp = await call_next(request)
    for k, v in cors_headers().items():
        resp.headers[k] = v
    resp.headers["X-Request-ID"] = rid
    resp.headers["X-Process-Time"] = f"{time.perf_counter() - t0:.6f}"
    return resp
