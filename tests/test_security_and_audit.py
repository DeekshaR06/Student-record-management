import os, re, sys, subprocess, json
os.environ.update(DB_HOST="127.0.0.1", DB_USER="tester", DB_PASSWORD="pw", DB_NAME="student_db", SECRET_KEY="k"*40)
sys.path.insert(0, ".")
import app as A

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

def post(c, url, data=None, ip="10.1.1.1", follow=True, token=None):
    d = dict(data or {})
    d["csrf_token"] = token if token is not None else tok(c)
    return c.post(url, data=d, headers={"X-Real-IP": ip}, follow_redirects=follow)

def login(c, u, p, ip="10.1.1.1"):
    c.get("/login")
    return post(c, "/login", {"username": u, "password": p}, ip=ip)

def last_audit(**f):
    where = " AND ".join(f"{k}=%s" for k in f)
    return A.query(f"SELECT * FROM audit_log WHERE {where} ORDER BY log_id DESC LIMIT 1", tuple(f.values()), one=True)

def n_audit():
    return A.query("SELECT COUNT(*) n FROM audit_log", one=True)["n"]

A.create_user("boss", "adminpass1", "admin")
A.create_user("view", "viewpass1", "viewer")
A.create_user("locktest", "lockpass12", "viewer")

# ---- authentication
anon = A.app.test_client()
r = anon.get("/"); ok("anonymous redirected to login", r.status_code == 302 and "/login" in r.location)
r = anon.get("/students"); ok("anonymous cannot see students", r.status_code == 302)
r = anon.get("/audit"); ok("anonymous cannot see audit", r.status_code == 302)
r = anon.post("/students/1/delete"); ok("POST without CSRF token rejected", r.status_code == 400)

h = A.query("SELECT password_hash FROM users WHERE username='boss'", one=True)["password_hash"]
ok("password stored as hash, not plaintext", "adminpass1" not in h and len(h) > 40)

c = A.app.test_client()
r = login(c, "boss", "wrongpass", ip="10.2.2.2"); ok("wrong password rejected", b"Invalid username or password" in r.data)
ok("failed login audited", last_audit(action="LOGIN_FAILED", username="boss") is not None)
r = c.get("/login?next=//evil.com")
r = post(c, "/login?next=//evil.com", {"username": "boss", "password": "adminpass1"}, follow=False)
ok("open redirect blocked", r.status_code == 302 and "evil.com" not in r.location)
ok("session cookie is HttpOnly", "HttpOnly" in r.headers.get("Set-Cookie", ""))
ok("login audited with IP", (last_audit(action="LOGIN", username="boss") or {}).get("ip_address") == "10.1.1.1")

lk = A.app.test_client()
for _ in range(5): login(lk, "locktest", "bad-password", ip="10.9.9.9")
r = login(lk, "locktest", "lockpass12", ip="10.9.9.9"); ok("account locked after 5 failures (even correct password)", r.status_code == 429)
ok("lockout audited", last_audit(action="LOGIN_BLOCKED") is not None)

# ---- admin session
r = c.get("/"); ok("admin sees dashboard", r.status_code == 200 and b"Enrollments per course" in r.data)
ok("security headers set", r.headers.get("X-Frame-Options") == "DENY" and r.headers.get("Cache-Control") == "no-store")
r = c.post("/students/1/delete", data={}); ok("admin POST without token rejected", r.status_code == 400)
r = post(c, "/students/1/delete", token="é"); ok("non-ASCII token rejected, no crash", r.status_code == 400)

before = n_audit()
r = post(c, "/students/add", {"first_name": "Zed", "last_name": "Test", "email": "zed@x.com", "phone": "111", "date_of_birth": "2004-01-01"})
a = last_audit(action="CREATE", entity="student"); ok("add student audited", a and "zed@x.com" in a["details"] and a["username"] == "boss")
zid = a["entity_id"]
r = post(c, f"/students/{zid}/edit", {"first_name": "Zed", "last_name": "Test", "email": "zed@x.com", "phone": "999", "date_of_birth": "2004-01-01"})
a = last_audit(action="UPDATE", entity="student"); d = json.loads(a["details"])
ok("edit student audited with before/after", d["phone"] == {"from": "111", "to": "999"} and list(d) == ["phone"])
n = n_audit()
post(c, f"/students/{zid}/edit", {"first_name": "Zed", "last_name": "Test", "email": "zed@x.com", "phone": "999", "date_of_birth": "2004-01-01"})
ok("no-change edit writes no audit row", n_audit() == n)
r = post(c, "/students/1/delete"); ok("delete blocked for enrolled student", b"Cannot delete" in r.data)
ok("blocked delete not audited as DELETE", last_audit(action="DELETE", entity="student", entity_id=1) is None)
r = post(c, f"/students/{zid}/delete"); a = last_audit(action="DELETE", entity="student")
ok("delete student audited with snapshot", a and "zed@x.com" in a["details"])

post(c, "/enrollments", {"student_id": "3", "course_id": "2", "grade": ""})
a = last_audit(action="CREATE", entity="enrollment"); ok("enroll audited", a is not None)
eid = a["entity_id"]
post(c, f"/enrollments/{eid}/grade", {"grade": "A"})
a = last_audit(action="UPDATE", entity="enrollment"); ok("grade change audited", json.loads(a["details"])["grade"]["to"] == "A")
post(c, f"/enrollments/{eid}/delete"); ok("enrollment delete audited", last_audit(action="DELETE", entity="enrollment", entity_id=eid) is not None)
post(c, "/courses", {"course_code": "ZZ1", "course_name": "Temp", "credits": "2"})
cid = last_audit(action="CREATE", entity="course")["entity_id"]
post(c, f"/courses/{cid}/delete"); ok("course create+delete audited", last_audit(action="DELETE", entity="course", entity_id=cid) is not None)

# ---- reports and audit page
r = c.get("/reports/student?student_id=1"); ok("reports work when logged in", b"CS101" in r.data)
r = c.get("/audit"); ok("admin sees audit report", r.status_code == 200 and b"LOGIN" in r.data and b"zed@x.com" in r.data)
r = c.get("/audit?action=DELETE"); import re as _re
_rows = _re.findall(r'<span class="pill [a-z_]+">([A-Z_]+)</span>', r.get_data(as_text=True).split("<table>")[1])
ok("audit filter by action", bool(_rows) and set(_rows) == {"DELETE"})
r = c.get("/audit?username=boss&entity=student"); ok("audit filter by user+record type", r.status_code == 200 and b"student" in r.data)
r = c.get("/audit?format=csv"); ok("audit CSV export", r.mimetype == "text/csv" and b"Time (UTC)" in r.data)

# ---- user management
r = post(c, "/users", {"username": "view", "password": "whatever12", "role": "viewer"}); ok("duplicate user rejected", b"already exists" in r.data)
r = post(c, "/users", {"username": "newbie", "password": "short", "role": "viewer"}); ok("short password rejected", b"at least 8" in r.data)
r = post(c, "/users", {"username": "a b", "password": "longenough1", "role": "viewer"}); ok("bad username rejected", b"Username must be" in r.data)
r = post(c, "/users", {"username": "temp", "password": "temppass12", "role": "viewer"}); ok("admin creates user", b"User created" in r.data)
bid = A.query("SELECT user_id FROM users WHERE username='boss'", one=True)["user_id"]
r = post(c, f"/users/{bid}/delete"); ok("admin cannot delete self", b"cannot delete your own" in r.data)

t = A.app.test_client(); login(t, "temp", "temppass12", ip="10.3.3.3")
ok("new user can sign in", t.get("/").status_code == 200)
tid = A.query("SELECT user_id FROM users WHERE username='temp'", one=True)["user_id"]
post(c, f"/users/{tid}/delete")
r = t.get("/"); ok("deleted user's session stops working", r.status_code == 302 and "/login" in r.location)
ok("audit history survives user deletion", last_audit(username="temp", action="LOGIN") is not None)

# ---- viewer restrictions
v = A.app.test_client(); login(v, "view", "viewpass1", ip="10.4.4.4")
r = v.get("/students"); ok("viewer sees students", r.status_code == 200 and b"Asha" in r.data and b"Add Student" not in r.data and b"Delete" not in r.data)
ok("viewer GET add student forbidden", v.get("/students/add").status_code == 403)
ok("viewer POST add student forbidden", post(v, "/students/add", {"first_name": "x", "last_name": "y", "email": "v@x.com"}, ip="10.4.4.4").status_code == 403)
ok("viewer POST delete forbidden", post(v, "/students/1/delete", ip="10.4.4.4").status_code == 403)
ok("viewer POST new course forbidden", post(v, "/courses", {"course_code": "V1", "course_name": "v", "credits": "1"}, ip="10.4.4.4").status_code == 403)
ok("viewer POST enroll forbidden", post(v, "/enrollments", {"student_id": "1", "course_id": "1"}, ip="10.4.4.4").status_code == 403)
ok("viewer cannot open audit", v.get("/audit").status_code == 403)
ok("viewer cannot open users", v.get("/users").status_code == 403)
ok("viewer can run reports", v.get("/reports/course?course_id=2").status_code == 200)
ok("viewer data unchanged", A.query("SELECT COUNT(*) n FROM students WHERE email='v@x.com'", one=True)["n"] == 0)

# ---- password change
r = post(v, "/account/password", {"current": "nope", "new": "newpassword1", "confirm": "newpassword1"}, ip="10.4.4.4"); ok("wrong current password rejected", b"incorrect" in r.data)
r = post(v, "/account/password", {"current": "viewpass1", "new": "newpassword1", "confirm": "different12"}, ip="10.4.4.4"); ok("mismatched confirmation rejected", b"do not match" in r.data)
r = post(v, "/account/password", {"current": "viewpass1", "new": "newpassword1", "confirm": "newpassword1"}, ip="10.4.4.4"); ok("password changed", b"Password changed" in r.data)
v2 = A.app.test_client(); r = login(v2, "view", "viewpass1", ip="10.5.5.5"); ok("old password no longer works", b"Invalid" in r.data)
v3 = A.app.test_client(); login(v3, "view", "newpassword1", ip="10.5.5.5"); ok("new password works", v3.get("/").status_code == 200)

# ---- logout
post(c, "/logout"); ok("logout ends session", c.get("/").status_code == 302)
ok("logout audited", last_audit(action="LOGOUT", username="boss") is not None)

# ---- config safety
res = subprocess.run([sys.executable, "-c", "import app"], env={**os.environ, "SECRET_KEY": "change-me"}, capture_output=True, text=True)
ok("app refuses weak SECRET_KEY", res.returncode != 0 and "SECRET_KEY" in res.stderr)
