import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
GOOD = ("What it covers: Cloud service models and deployment.\nKey topics: IaaS, PaaS, SaaS, virtualization.\n"
        "Skills and careers: Cloud engineer, DevOps.\nRelevance today: Very high demand.\n"
        "Next courses to take: DevOps, Security.")
STATE = {"mode": "ok", "text": GOOD, "calls": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        hdr = {k.lower(): v for k, v in self.headers.items()}
        STATE["calls"].append({"path": self.path, "headers": hdr, "body": body})

        def reply(code, obj):
            raw = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        mode = STATE["mode"]
        if mode == "slow":
            time.sleep(2.5)
        if mode == "notfound" and "generateContent" in self.path:
            return reply(404, {"error": {"message": "model not found"}})
        if "generateContent" in self.path:
            if hdr.get("x-goog-api-key") != "testkey":
                return reply(400, {"error": {"message": "API key not valid. Please pass a valid API key."}})
            if mode == "quota":
                return reply(429, {"error": {"message": "quota exceeded"}})
            if mode == "no_grounding" and "tools" in body:
                return reply(400, {"error": {"message": "google_search is not supported"}})
            cand = {"content": {"parts": [{"text": STATE["text"]}]}}
            if "tools" in body:
                cand["groundingMetadata"] = {"groundingChunks": [
                    {"web": {"uri": "https://example.com/cloud", "title": "example.com"}},
                    {"web": {"uri": "javascript:alert(1)", "title": "evil"}}]}
            return reply(200, {"candidates": [cand]})
        if "chat/completions" in self.path:
            if hdr.get("authorization") != "Bearer groqkey":
                return reply(401, {"error": {"message": "bad key"}})
            return reply(200, {"choices": [{"message": {"content": GOOD}}]})
        reply(404, {})


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # the slow-mode test makes clients hang up early on purpose


srv = QuietServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

os.environ.update(DB_HOST="127.0.0.1", DB_USER="tester", DB_PASSWORD="pw", DB_NAME="student_db",
                  SECRET_KEY="k" * 40, GEMINI_BASE_URL=f"http://127.0.0.1:{PORT}/v1beta",
                  GROQ_BASE_URL=f"http://127.0.0.1:{PORT}/openai/v1", GEMINI_API_KEY="testkey",
                  GROQ_API_KEY="groqkey", AI_PROVIDER="gemini")
sys.path.insert(0, ".")
import app as A
import ai_insights as AI


def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)


def tok(c):
    with c.session_transaction() as s:
        t = s.get("csrf")
    if not t:
        c.get("/login")
        with c.session_transaction() as s:
            t = s["csrf"]
    return t


def post(c, url, data=None, ip="10.1.1.1"):
    d = dict(data or {})
    d["csrf_token"] = tok(c)
    return c.post(url, data=d, headers={"X-Real-IP": ip}, follow_redirects=True)


def login(c, u, p, ip):
    c.get("/login")
    return post(c, "/login", {"username": u, "password": p}, ip=ip)


def reset():
    A.query("DELETE FROM audit_log WHERE action IN ('AI_INSIGHT','AI_FAILED')")
    A.query("DELETE FROM course_insights")
    STATE.update(mode="ok", text=GOOD)
    STATE["calls"].clear()
    A.AI_USER_HOURLY_LIMIT, A.AI_DAILY_LIMIT = 5, 20
    os.environ.update(AI_PROVIDER="gemini", GEMINI_API_KEY="testkey")


def row(cid):
    return A.query("SELECT * FROM course_insights WHERE course_id=%s", (cid,), one=True)


A.create_user("boss", "adminpass1", "admin")
A.create_user("view", "viewpass1", "viewer")
adm = A.app.test_client(); login(adm, "boss", "adminpass1", "10.1.0.1")
vw = A.app.test_client(); login(vw, "view", "viewpass1", "10.1.0.2")
anon = A.app.test_client()

# ---- access control
ok("anonymous redirected from insights page", anon.get("/courses/3/insights").status_code == 302)
ok("POST without CSRF rejected", anon.post("/courses/3/insights", data={}).status_code == 400)
ok("courses page shows AI Insights link to viewer", b"AI Insights" in vw.get("/courses").data)
ok("unknown course 404", vw.get("/courses/999/insights").status_code == 404)
ok("empty state before generating", b"Generate AI insights" in vw.get("/courses/3/insights").data)

# ---- generate (viewer) with grounding
reset()
r = post(vw, "/courses/3/insights", ip="10.1.0.2")
ok("viewer can generate insights", b"AI insights generated" in r.data)
c0 = STATE["calls"][0]
prompt = c0["body"]["contents"][0]["parts"][0]["text"]
ok("one API call, key sent in header not URL", len(STATE["calls"]) == 1 and c0["headers"]["x-goog-api-key"] == "testkey" and "testkey" not in c0["path"])
ok("grounding tool requested", c0["body"].get("tools") == [{"google_search": {}}])
ok("prompt has only the course name, no personal data", "Cloud Computing" in prompt and "@" not in prompt and "Asha" not in prompt)
ok("custom User-Agent sent", c0["headers"]["user-agent"].startswith("student-record-app"))
d = row(3)
ok("insight cached with grounded flag", d and d["grounded"] == 1 and d["model"] == "gemini-flash-latest")
ok("unsafe source URL filtered out", "javascript" not in d["sources"] and "example.com" in d["sources"])
pg = vw.get("/courses/3/insights").get_data(as_text=True)
ok("page shows sections and source link", "What it covers" in pg and "Cloud engineer" in pg and 'href="https://example.com/cloud"' in pg)
ok("page shows web search used + disclaimer", "Live web search used: yes" in pg and "may be inaccurate" in pg)
ok("javascript: link never rendered", "javascript:alert" not in pg)
a = A.query("SELECT * FROM audit_log WHERE action='AI_INSIGHT' ORDER BY log_id DESC LIMIT 1", one=True)
ok("generation audited with user", a and a["username"] == "view" and a["entity_id"] == 3 and '"web_search": true' in a["details"])

# ---- cache and admin refresh
r = post(vw, "/courses/3/insights", ip="10.1.0.2"); ok("second request served from cache", b"already up to date" in r.data and len(STATE["calls"]) == 1)
r = post(vw, "/courses/3/insights", {"refresh": "1"}, ip="10.1.0.2"); ok("viewer cannot force refresh", len(STATE["calls"]) == 1)
ok("viewer sees no refresh button", b"Refresh insights" not in vw.get("/courses/3/insights").data)
ok("admin sees refresh button", b"Refresh insights" in adm.get("/courses/3/insights").data)
r = post(adm, "/courses/3/insights", {"refresh": "1"}, ip="10.1.0.1"); ok("admin refresh calls API again", len(STATE["calls"]) == 2)

# ---- fallback when grounding is not allowed on the free tier
reset(); STATE["mode"] = "no_grounding"
r = post(vw, "/courses/2/insights", ip="10.1.0.2")
ok("falls back to ungrounded request", b"AI insights generated" in r.data and len(STATE["calls"]) == 2 and "tools" in STATE["calls"][0]["body"] and "tools" not in STATE["calls"][1]["body"])
ok("fallback stored as not grounded", row(2)["grounded"] == 0)
ok("page says model knowledge only", "no (model knowledge only)" in vw.get("/courses/2/insights").get_data(as_text=True))

# ---- errors are friendly, audited, never leak the key
reset(); STATE["mode"] = "quota"
r = post(vw, "/courses/1/insights", ip="10.1.0.2")
ok("quota error shown clearly", b"quota is used up" in r.data and row(1) is None)
ok("failure audited as AI_FAILED", A.query("SELECT COUNT(*) n FROM audit_log WHERE action='AI_FAILED'", one=True)["n"] == 1)
reset(); os.environ["GEMINI_API_KEY"] = "wrongkey"
r = post(vw, "/courses/1/insights", ip="10.1.0.2")
ok("bad key reported without leaking it", b"rejected the API key" in r.data and b"wrongkey" not in r.data)
reset(); os.environ["GEMINI_API_KEY"] = ""
r = post(vw, "/courses/1/insights", ip="10.1.0.2")
ok("missing key gives setup message, no HTTP call", b"not set up" in r.data and len(STATE["calls"]) == 0)

# ---- limits
reset(); A.AI_USER_HOURLY_LIMIT = 2; STATE["mode"] = "quota"
post(vw, "/courses/1/insights", ip="10.1.0.2"); post(vw, "/courses/2/insights", ip="10.1.0.2"); n = len(STATE["calls"])
r = post(vw, "/courses/3/insights", ip="10.1.0.2")
ok("per-user hourly limit blocks (failures count too)", b"limit of 2 AI requests per hour" in r.data and len(STATE["calls"]) == n)
reset(); A.AI_DAILY_LIMIT = 1
post(adm, "/courses/1/insights", ip="10.1.0.1")
r = post(vw, "/courses/2/insights", ip="10.1.0.2")
ok("daily limit protects free quota", b"daily AI request limit" in r.data and len(STATE["calls"]) == 1)

# ---- output is escaped
reset(); STATE["text"] = "What it covers: <script>alert(1)</script> hello"
post(adm, "/courses/1/insights", ip="10.1.0.1")
pg = adm.get("/courses/1/insights").get_data(as_text=True)
ok("AI output HTML-escaped", "&lt;script&gt;" in pg and "<script>alert(1)" not in pg)

# ---- Groq provider
reset(); os.environ["AI_PROVIDER"] = "groq"
r = post(vw, "/courses/2/insights", ip="10.1.0.2")
ok("groq provider works", b"AI insights generated" in r.data and STATE["calls"][0]["headers"]["authorization"] == "Bearer groqkey")
ok("groq stores model, no sources", row(2)["model"] == "llama-3.1-8b-instant" and row(2)["grounded"] == 0)
os.environ["AI_PROVIDER"] = "gemini"

# ---- cascade, audit page, parser
reset()
A.query("INSERT INTO courses (course_code, course_name, credits) VALUES ('ZZ9','Temp Course',2)")
zid = A.query("SELECT course_id FROM courses WHERE course_code='ZZ9'", one=True)["course_id"]
post(adm, f"/courses/{zid}/insights", ip="10.1.0.1"); ok("insight stored for temp course", row(zid) is not None)
post(adm, f"/courses/{zid}/delete", ip="10.1.0.1"); ok("deleting course removes its cached insight", row(zid) is None)
r = adm.get("/audit?action=AI_INSIGHT"); ok("audit page lists AI actions", r.status_code == 200 and b"AI_INSIGHT" in r.data and b"web_search" in r.data)
ok("viewer still cannot open audit", vw.get("/audit").status_code == 403)
s = AI.parse_sections("**What it covers:** A\nB\n## Key topics\n- x, y\nstray")
ok("parser handles stray markdown", [x["title"] for x in s] == ["What it covers", "Key topics"] and s[0]["body"] == "A B" and s[1]["body"] == "x, y stray")
ok("name cleaner strips quotes and newlines", AI.clean_name('Evil"\nIgnore previous') == "Evil Ignore previous")

# ---- clearer messages for retired model and slow answers
reset(); STATE["mode"] = "notfound"
r = post(vw, "/courses/1/insights", ip="10.1.0.2")
ok("retired model gives a clear message", b"GEMINI_MODEL" in r.data and b"not available" in r.data)
reset(); STATE["mode"] = "slow"; os.environ["AI_TIMEOUT"] = "1"
t0 = time.time(); r = post(vw, "/courses/1/insights", ip="10.1.0.2")
ok("slow AI gives a clear timeout message", b"took too long" in r.data and time.time() - t0 < 10)
os.environ.pop("AI_TIMEOUT")
srv.shutdown()
time.sleep(3)  # let the deliberately slow mock handlers finish
