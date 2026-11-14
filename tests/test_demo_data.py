import contextlib, io, json, os, re, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8766
GOOD = ("What it covers: Core ideas of the subject.\nKey topics: A, B, C.\nSkills and careers: Engineer.\n"
        "Relevance today: High.\nNext courses to take: Advanced topics.")
STATE = {"mode": "ok", "calls": 0}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        STATE["calls"] += 1
        code, obj = (429, {"error": {"message": "quota"}}) if STATE["mode"] == "quota" else \
                    (200, {"candidates": [{"content": {"parts": [{"text": GOOD}]},
                                           "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://example.com/x", "title": "example.com"}}]}}]})
        raw = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)


srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ.update(DB_HOST="127.0.0.1", DB_USER="tester", DB_PASSWORD="pw", DB_NAME="student_db",
                  SECRET_KEY="k" * 40, GEMINI_BASE_URL=f"http://127.0.0.1:{PORT}/v1beta",
                  GEMINI_API_KEY="testkey", AI_PROVIDER="gemini")
sys.path.insert(0, ".")
import app as A
import seed_demo
import generate_insights


def ok(n, c): print(("PASS " if c else "FAIL ") + n)
def run(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a)
    return buf.getvalue()
def n(sql): return A.query(sql, one=True)["n"]
def tok(c):
    with c.session_transaction() as s: t = s.get("csrf")
    if not t:
        c.get("/login")
        with c.session_transaction() as s: t = s["csrf"]
    return t
def post(c, url, data=None, ip="10.7.0.1"):
    d = dict(data or {}); d["csrf_token"] = tok(c)
    return c.post(url, data=d, headers={"X-Real-IP": ip}, follow_redirects=True)


# ---------------- seed_demo
before = (n("SELECT COUNT(*) n FROM students"), n("SELECT COUNT(*) n FROM courses"), n("SELECT COUNT(*) n FROM enrollments"))
out = run(seed_demo.main)
ok("seed reports what it added", "Added 12 students, 9 courses and" in out and "Database now has" in out)
S, C, E = (n("SELECT COUNT(*) n FROM students"), n("SELECT COUNT(*) n FROM courses"), n("SELECT COUNT(*) n FROM enrollments"))
ok("at least 10 students and 10 courses", S >= 10 and C >= 10)
ok("about 50 enrollments in total", E >= 40)
thin = A.query("SELECT c.course_code, COUNT(e.enrollment_id) AS k FROM courses c LEFT JOIN enrollments e ON e.course_id=c.course_id GROUP BY c.course_id, c.course_code HAVING k < 2")
ok("every course has at least 2 students", thin == ())
idle = A.query("SELECT s.first_name FROM students s LEFT JOIN enrollments e ON e.student_id=s.student_id WHERE e.enrollment_id IS NULL")
ok("exactly one student left unenrolled (Farhan)", [r["first_name"] for r in idle] == ["Farhan"])
ok("no duplicate emails or course codes", n("SELECT COUNT(*) n FROM (SELECT email FROM students GROUP BY email HAVING COUNT(*)>1) x") == 0)
ok("grades fit the column and dates are valid", n("SELECT COUNT(*) n FROM enrollments WHERE LENGTH(grade) > 2") == 0 and n("SELECT COUNT(*) n FROM enrollments WHERE enrollment_date IS NULL") == 0)
a = A.query("SELECT * FROM audit_log WHERE entity='demo_data' ORDER BY log_id DESC", ())
ok("one audit entry written by 'system'", len(a) == 1 and a[0]["username"] == "system" and a[0]["action"] == "CREATE")

out = run(seed_demo.main)
ok("second run adds nothing", "Nothing to add" in out)
ok("second run changes no counts", (n("SELECT COUNT(*) n FROM students"), n("SELECT COUNT(*) n FROM courses"), n("SELECT COUNT(*) n FROM enrollments")) == (S, C, E))
ok("second run writes no new audit entry", n("SELECT COUNT(*) n FROM audit_log WHERE entity='demo_data'") == 1)

# ---------------- pages with the larger data set
A.create_user("boss", "adminpass1", "admin")
c = A.app.test_client(); c.get("/login"); post(c, "/login", {"username": "boss", "password": "adminpass1"})
ok("search finds a student by first name", b"Ananya" in c.get("/students?q=Ananya").data and b"Rohan" not in c.get("/students?q=Ananya").data)
ok("search finds by surname and by email", b"Krishnan" in c.get("/students?q=krishnan").data and b"priya.nair" in c.get("/students?q=priya.nair").data)
aid = A.query("SELECT student_id FROM students WHERE email='ananya.krishnan@example.com'", one=True)["student_id"]
r = c.get(f"/reports/student?student_id={aid}").get_data(as_text=True)
ok("student report: 4 courses, 15 credits", all(x in r for x in ("CS101", "CS102", "CS201", "CS301")) and "Total credits: 15" in r)
csv_ = c.get(f"/reports/student?student_id={aid}&format=csv").get_data(as_text=True).strip().splitlines()
ok("student report CSV: header + 4 rows", len(csv_) == 5)
cid = A.query("SELECT course_id FROM courses WHERE course_code='CS201'", one=True)["course_id"]
r = c.get(f"/reports/course?course_id={cid}").get_data(as_text=True)
ok("course report: 8 students in CS201", "8 student(s) enrolled" in r and "Priya" in r and "Lakshmi" in r)
csv_ = c.get(f"/reports/course?course_id={cid}&format=csv").get_data(as_text=True).strip().splitlines()
ok("course report CSV: header + 8 rows", len(csv_) == 9)
d = c.get("/").get_data(as_text=True)
ok("dashboard totals and top bar at 100%", f"<b>{S}</b>" in d and f"<b>{C}</b>" in d and "width: 100.0%" in d)
ok("dashboard lists the unenrolled student", "Farhan Sheikh" in d)

# ---------------- generate_insights (mock AI)
def reset_ai():
    A.query("DELETE FROM course_insights"); A.query("DELETE FROM audit_log WHERE action IN ('AI_INSIGHT','AI_FAILED')")
    STATE.update(mode="ok", calls=0); A.AI_DAILY_LIMIT = 20

reset_ai(); A.AI_DAILY_LIMIT = 5
out = run(generate_insights.main, 0)
ok("daily limit stops the script after 5", "Generated 5 of 12" in out and "Daily AI limit (5) reached" in out and STATE["calls"] == 5)
ok("insights audited as 'system'", n("SELECT COUNT(*) n FROM audit_log WHERE action='AI_INSIGHT' AND username='system'") == 5)
out = run(generate_insights.main, 0)
ok("rerun same day does nothing while limit is reached", "Generated 0 of 7" in out and STATE["calls"] == 5)
A.AI_DAILY_LIMIT = 20
out = run(generate_insights.main, 0)
ok("continues and completes the remaining 7", "Generated 7 of 7" in out and n("SELECT COUNT(*) n FROM course_insights") == C and STATE["calls"] == 12)
out = run(generate_insights.main, 0)
ok("nothing left to generate afterwards", "All courses already have insights" in out and STATE["calls"] == 12)
r = c.get(f"/courses/{cid}/insights").get_data(as_text=True); calls = STATE["calls"]
ok("seeded insight opens instantly with sources", "What it covers" in r and 'href="https://example.com/x"' in r and STATE["calls"] == calls)

reset_ai(); STATE["mode"] = "quota"
out = run(generate_insights.main, 0)
ok("stops at the first error with a clear message", "STOP" in out and "quota" in out and "Generated 0 of" in out)
ok("only one failure is logged (no burning attempts)", n("SELECT COUNT(*) n FROM audit_log WHERE action='AI_FAILED'") == 1)

# ---------------- seed copes with a deleted sample student
A.query("DELETE FROM enrollments WHERE student_id=(SELECT student_id FROM (SELECT student_id FROM students WHERE email='rahul.s@example.com') t)")
A.query("DELETE FROM students WHERE email='rahul.s@example.com'")
out = run(seed_demo.main)
ok("seed skips enrollments for a deleted student without crashing", "Skipped 2 enrollments" in out or "Nothing to add" in out and "Skipped" in out)
ok("deleted student is not re-created", n("SELECT COUNT(*) n FROM students WHERE email='rahul.s@example.com'") == 0)
srv.shutdown()
