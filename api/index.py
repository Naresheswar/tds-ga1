import hashlib
import json
import os
import re
import time
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI()
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ga2  # noqa: E402
app.include_router(ga2.router)
app.middleware("http")(ga2.middleware)

EMAIL = "24f3002833@ds.study.iitm.ac.in"


@app.get("/")
def root():
    return {"ok": True, "endpoints": ["/effective-config", "/mcp", "/ledger"]}


# ---------------------------------------------------------------------------
# Q: 12-factor config precedence
# ---------------------------------------------------------------------------
DEFAULTS = {"port": 8000, "workers": 1, "debug": False, "log_level": "info", "api_key": "default-secret-000"}
YAML_LAYER = {"port": "8858", "debug": "true", "log_level": "error"}            # config.development.yaml
DOTENV_RAW = {"APP_API_KEY": "key-j51s2tnto7"}                                 # .env
OSENV_RAW = {"APP_PORT": "8723", "APP_DEBUG": "false", "APP_LOG_LEVEL": "error"}  # OS env (APP_*)


def _env_to_keys(raw):
    out = {}
    for k, v in raw.items():
        if k.upper() == "NUM_WORKERS":
            out["workers"] = v
        elif k.upper().startswith("APP_"):
            key = k[4:].lower()
            out["workers" if key == "num_workers" else key] = v
    return out


def _coerce(key, value):
    if key in ("port", "workers"):
        return int(str(value).strip())
    if key == "debug":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    return str(value)


@app.get("/effective-config")
def effective_config(request: Request):
    merged = dict(DEFAULTS)
    merged.update(YAML_LAYER)
    merged.update(_env_to_keys(DOTENV_RAW))
    merged.update(_env_to_keys(OSENV_RAW))
    for item in request.query_params.getlist("set"):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip().lower()
        if k in ("num_workers",):
            k = "workers"
        merged[k] = v
    out = {k: _coerce(k, v) for k, v in merged.items()}
    out["api_key"] = "****"
    return out


# ---------------------------------------------------------------------------
# Q: Live MCP server (streamable HTTP, JSON responses)
# ---------------------------------------------------------------------------
TOOL = {
    "name": "solve_challenge",
    "description": "Return the first 16 hex chars of SHA-256(challenge:email), reading the challenge from the X-Exam-Challenge header.",
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}


def _mcp_result(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _mcp_handle(msg, request):
    method = msg.get("method")
    req_id = msg.get("id")
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        return _mcp_result(req_id, {
            "protocolVersion": pv,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "tds-ga1-mcp", "version": "1.0.0"},
        })
    if method and method.startswith("notifications/"):
        return None
    if method == "ping":
        return _mcp_result(req_id, {})
    if method == "tools/list":
        return _mcp_result(req_id, {"tools": [TOOL]})
    if method == "tools/call":
        name = (msg.get("params") or {}).get("name")
        if name != "solve_challenge":
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown tool {name}"}}
        challenge = request.headers.get("x-exam-challenge", "")
        text = hashlib.sha256(f"{challenge}:{EMAIL}".encode()).hexdigest()[:16]
        return _mcp_result(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
    if req_id is None:
        return None
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


@app.post("/mcp")
@app.post("/mcp/")
async def mcp_post(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
    headers = {"Mcp-Session-Id": request.headers.get("mcp-session-id") or "tds-ga1-session"}
    if isinstance(body, list):
        out = [r for r in (_mcp_handle(m, request) for m in body) if r is not None]
        if not out:
            return Response(status_code=202, headers=headers)
        return JSONResponse(out, headers=headers)
    out = _mcp_handle(body, request)
    if out is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(out, headers=headers)


@app.get("/mcp")
@app.get("/mcp/")
def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.delete("/mcp")
def mcp_delete():
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Q: The Ledger Agent
# ---------------------------------------------------------------------------
LEDGER_BASE = os.environ.get("LEDGER_URL", "")
IST = timezone(timedelta(hours=5, minutes=30))
_CACHE = {"t": 0, "orders": None, "rates": None}

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
MONTH_ABBR = {m[:3]: i for m, i in MONTHS.items()}
MONTH_ABBR["sept"] = 9


def _get(path):
    url = f"{LEDGER_BASE}&path={urllib.parse.quote(path, safe='')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        "Accept": "application/json, application/x-ndjson, */*",
    })
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read().decode()



def _parse_ts(s):
    s = str(s).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        d = datetime.fromisoformat(s[:19])
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def load():
    if _CACHE["orders"] is not None and time.time() - _CACHE["t"] < 600:
        return _CACHE["orders"], _CACHE["rates"]
    rates = json.loads(_get("/rates"))
    rates = rates.get("usd_per_unit", rates)
    raw = [json.loads(l) for l in _get("/export").splitlines() if l.strip()]
    latest = {}
    for r in raw:
        u = _parse_ts(r.get("updated_at") or r.get("created_at"))
        if r["id"] not in latest or u >= latest[r["id"]][0]:
            latest[r["id"]] = (u, r)
    orders = []
    for _, r in latest.values():
        r = dict(r)
        r["status"] = str(r.get("status", "")).strip().lower()
        r["region"] = str(r.get("region", "")).strip()
        r["product"] = str(r.get("product", "")).strip()
        r["customer"] = str(r.get("customer", "")).strip()
        cur = str(r.get("currency", "USD")).strip().upper()
        r["usd"] = float(r["amount"]) * float(rates.get(cur, 1))
        r["qty"] = float(r.get("qty") or 0)
        r["date"] = _parse_ts(r["created_at"]).astimezone(IST).date()
        orders.append(r)
    _CACHE.update(t=time.time(), orders=orders, rates=rates)
    return orders, rates


def _month_range(y, m):
    start = datetime(y, m, 1).date()
    end = datetime(y + (m == 12), m % 12 + 1, 1).date()
    return start, end


def parse_dates(q):
    """Return (start, end_exclusive) or None."""
    years = [int(y) for y in re.findall(r"\b(20\d\d)\b", q)]
    default_year = years[0] if years else 2026
    # explicit ISO dates
    iso = re.findall(r"\b(20\d\d)-(\d\d)-(\d\d)\b", q)
    if len(iso) >= 2:
        a = datetime(*map(int, iso[0])).date()
        b = datetime(*map(int, iso[1])).date()
        return a, b + timedelta(days=1)
    # quarters
    mq = re.search(r"\bq([1-4])\b", q) or re.search(r"\b(first|second|third|fourth) quarter\b", q)
    if mq:
        qn = {"first": 1, "second": 2, "third": 3, "fourth": 4}.get(mq.group(1), None) or int(mq.group(1))
        s, _ = _month_range(default_year, 3 * qn - 2)
        _, e = _month_range(default_year, 3 * qn)
        return s, e
    if re.search(r"\bh1\b|first half", q):
        return _month_range(default_year, 1)[0], _month_range(default_year, 6)[1]
    if re.search(r"\bh2\b|second half", q):
        return _month_range(default_year, 7)[0], _month_range(default_year, 12)[1]
    # month names (full or abbreviated)
    found = []
    for tok in re.finditer(r"\b([a-z]+)\b", q):
        w = tok.group(1)
        if w in MONTHS:
            found.append((tok.start(), MONTHS[w]))
        elif w in MONTH_ABBR and w not in ("mar", "may") or w in ("mar",):
            if w in MONTH_ABBR:
                found.append((tok.start(), MONTH_ABBR[w]))
    # numeric month forms like 2026-03 or 03/2026
    for mm in re.finditer(r"\b(20\d\d)-(\d\d)\b(?!-)", q):
        found.append((mm.start(), int(mm.group(2))))
    for mm in re.finditer(r"\b(\d{1,2})/(20\d\d)\b", q):
        found.append((mm.start(), int(mm.group(1))))
    found.sort()
    months = [m for _, m in found]
    if not months:
        if years:
            return datetime(years[0], 1, 1).date(), datetime(years[-1] + 1, 1, 1).date()
        return None
    y1 = years[0] if years else default_year
    y2 = years[-1] if years else default_year
    if len(months) >= 2 and re.search(r"\b(between|from|through|thru|to|until|till)\b|[-–]", q):
        return _month_range(y1, months[0])[0], _month_range(y2, months[-1])[1]
    if len(months) >= 2:
        # e.g. "in March and April" -> span
        return _month_range(y1, min(months))[0], _month_range(y2, max(months))[1]
    return _month_range(y1, months[0])


def _pick(q, values):
    hits = []
    for v in values:
        if re.search(r"\b" + re.escape(v.lower()) + r"s?\b", q):
            hits.append(v)
    return hits


def answer_question(question):
    orders, _ = load()
    q = question.lower().replace("’", "'")
    regions = sorted({o["region"] for o in orders})
    products = sorted({o["product"] for o in orders}, key=len, reverse=True)
    reg = _pick(q, regions)
    prod = []
    qtmp = q
    for p in products:
        if re.search(r"\b" + re.escape(p.lower()) + r"s?\b", qtmp):
            prod.append(p)
            qtmp = re.sub(r"\b" + re.escape(p.lower()) + r"s?\b", " ", qtmp)
    cust = [c.upper() for c in re.findall(r"\bc\d{3,}\b", q)]
    rng = parse_dates(q)

    def filt(rows, status=None):
        out = []
        for o in rows:
            if reg and o["region"] not in reg:
                continue
            if prod and o["product"] not in prod:
                continue
            if cust and o["customer"].upper() not in cust:
                continue
            if rng and not (rng[0] <= o["date"] < rng[1]):
                continue
            if status and o["status"] not in status:
                continue
            out.append(o)
        return out

    is_refund = bool(re.search(r"refund", q))
    is_void = bool(re.search(r"\bvoid", q))
    if is_refund:
        status = {"refunded"}
    elif is_void:
        status = {"void"}
    else:
        status = {"paid"}
    if re.search(r"how many|number of|count", q) and re.search(r"\ball\b|any status|regardless", q):
        status = None

    # grouping questions: which product/customer/region ...
    group_field = None
    if re.search(r"\bwhich (product|item)|top product|best[- ]selling|most popular product|product (had|has|with|generated|brought)|what product", q):
        group_field = "product"
    elif re.search(r"\bwhich customer|top customer|what customer|customer (had|has|with|spent|generated)|biggest customer|best customer", q):
        group_field = "customer"
    elif re.search(r"\bwhich region|top region|what region|region (had|has|with|generated)", q):
        group_field = "region"
    elif re.search(r"\bwhich month|what month", q):
        group_field = "month"
    if group_field == "product" and prod and not re.search(r"\bwhich|top|best|most|least|highest|lowest", q):
        group_field = None

    units = bool(re.search(r"\bunits?\b|quantity|qty|items sold|pieces", q))
    count_mode = bool(re.search(r"how many|number of|count of|\bcount\b", q)) and not units
    avg_mode = bool(re.search(r"average|avg|mean", q))
    lowest = bool(re.search(r"\b(least|lowest|fewest|smallest|minimum|min|worst)\b", q))

    rows = filt(orders, status)

    def metric(rs):
        if units:
            return sum(o["qty"] for o in rs)
        if count_mode:
            return len(rs)
        if avg_mode:
            return (sum(o["usd"] for o in rs) / len(rs)) if rs else 0
        return sum(o["usd"] for o in rs)

    if group_field:
        if group_field in ("product", "region", "customer"):
            prod_bak = None
        groups = defaultdict(list)
        base = orders
        for o in filt(base, status):
            key = o[group_field] if group_field != "month" else o["date"].strftime("%B")
            groups[key].append(o)
        if not groups:
            return None
        scored = sorted(groups.items(), key=lambda kv: (metric(kv[1]), kv[0]), reverse=not lowest)
        if lowest:
            scored = sorted(groups.items(), key=lambda kv: (metric(kv[1]), kv[0]))
        return scored[0][0]

    if re.search(r"distinct|unique", q) and re.search(r"customer", q):
        return len({o["customer"] for o in rows})

    val = metric(rows)
    if units or count_mode:
        return int(round(val))
    return round(val + 1e-9, 2)


@app.post("/ledger")
@app.post("/")
async def ledger(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    question = (body or {}).get("question", "")
    try:
        ans = answer_question(question)
    except Exception as e:  # keep the service answering
        return JSONResponse({"answer": None, "error": str(e)})
    return {"answer": ans}
