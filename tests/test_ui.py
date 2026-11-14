import os, re, sys
os.environ.update(DB_HOST="127.0.0.1", DB_USER="tester", DB_PASSWORD="pw", DB_NAME="student_db", SECRET_KEY="k"*40)
sys.path.insert(0, ".")
import app as A

def ok(n, c): print(("PASS " if c else "FAIL ") + n)
def tok(c):
    with c.session_transaction() as s: t = s.get("csrf")
    if not t:
        c.get("/login")
        with c.session_transaction() as s: t = s["csrf"]
    return t
def post(c, url, data=None, ip="10.1.1.1"):
    d = dict(data or {}); d["csrf_token"] = tok(c)
    return c.post(url, data=d, headers={"X-Real-IP": ip}, follow_redirects=True)
def login(c, u, p, ip):
    c.get("/login"); return post(c, "/login", {"username": u, "password": p}, ip=ip)
def html(c, url): return c.get(url).get_data(as_text=True)
def active(h): return re.findall(r'<a href="([^"]+)" class="active"', h)

A.create_user("boss", "adminpass1", "admin"); A.create_user("view", "viewpass1", "viewer")
adm = A.app.test_client(); login(adm, "boss", "adminpass1", "10.6.0.1")
vw = A.app.test_client(); login(vw, "view", "viewpass1", "10.6.0.2")
anon = A.app.test_client()

r = anon.get("/static/style.css"); css = r.get_data(as_text=True)
ok("stylesheet served before login", r.status_code == 200 and r.mimetype == "text/css")
ok("theme colours defined (navy, cream, coral)", all(v in css for v in ("--navy:#14284B", "--cream:#FBF5E9", "--coral:#FF6B57")))
lg = html(anon, "/login")
ok("login page: viewport, theme class, stylesheet, no top bar", 'name="viewport"' in lg and "login-page" in lg and "/static/style.css" in lg and 'class="topbar"' not in lg)

ok("Dashboard tab highlighted", active(html(adm, "/")) == ["/"])
ok("Students tab highlighted (also on edit page)", active(html(adm, "/students")) == ["/students"] and active(html(adm, "/students/1/edit")) == ["/students"])
ok("Courses tab highlighted on insights page", active(html(adm, "/courses/1/insights")) == ["/courses"])
ok("Enrollments tab highlighted", active(html(adm, "/enrollments")) == ["/enrollments"])
ok("Users and Audit tabs highlighted", active(html(adm, "/users")) == ["/users"] and active(html(adm, "/audit")) == ["/audit"])
for u in ("/reports/student", "/reports/course"):
    h = html(adm, u); ok(f"Reports menu highlighted on {u}", 'class="dd active"' in h and active(h) == [])
ok("Reports menu not highlighted elsewhere", 'class="dd active"' not in html(adm, "/students"))

a, v = html(adm, "/"), html(vw, "/")
ok("admin sees ADMIN badge, viewer sees VIEWER badge", 'class="role admin">ADMIN<' in a and 'class="role viewer">VIEWER<' in v)
ok("admin nav has Users and Audit Log", 'href="/users"' in a and 'href="/audit"' in a)
ok("viewer nav hides Users and Audit Log", 'href="/users"' not in v and 'href="/audit"' not in v)
ok("account menu has password change and logout with CSRF", 'href="/account/password"' in v and re.search(r'action="/logout"><input type="hidden" name="csrf_token"', v) is not None)

bars = [float(x) for x in re.findall(r'style="width: ([0-9.]+)%"', a)]
ok("dashboard bars scale to 100% for the top course", bars and max(bars) == 100.0 and all(0 <= b <= 100 for b in bars))
ok("dashboard stat cards present", a.count('class="stat ') == 3)

post(adm, "/students/add", {"first_name": "<b>x</b>", "last_name": "Y", "email": "xss@x.com", "phone": "", "date_of_birth": ""}, ip="10.6.0.1")
sp = html(adm, "/students")
ok("user-entered HTML is escaped on the page", "&lt;b&gt;x&lt;/b&gt;" in sp and "<b>x</b>" not in sp)
ok("search box present", 'placeholder="Search by ID, name or email"' in sp)

au = html(adm, "/audit")
ok("audit actions shown as colour-coded pills", 'class="pill login"' in au and 'class="pill create"' in au)
ok("users page shows role pills", 'class="pill admin"' in html(adm, "/users") and 'class="pill viewer"' in html(adm, "/users"))
r = vw.get("/audit"); ok("styled error page for forbidden access", r.status_code == 403 and 'class="errcode"' in r.get_data(as_text=True))
ok("static files carry security headers", anon.get("/static/style.css").headers.get("X-Content-Type-Options") == "nosniff")

bad = []
for u in ("/students", "/students/add", "/courses", "/enrollments", "/users", "/account/password", "/courses/1/insights"):
    h = html(adm, u)
    if len(re.findall(r'<form[^>]*method="post"', h)) != h.count('name="csrf_token"'): bad.append(u)
ok("every POST form has a CSRF token" + (f" (missing on {bad})" if bad else ""), not bad)
ok("viewer pages contain no delete/edit controls", all(w not in html(vw, u) for u in ("/students", "/courses", "/enrollments") for w in ("Delete", "Remove", "/edit")))
ok("all main pages load for admin", all(adm.get(u).status_code == 200 for u in ("/", "/students", "/courses", "/enrollments", "/users", "/audit", "/reports/student", "/reports/course", "/account/password")))
ok("all main pages load for viewer", all(vw.get(u).status_code == 200 for u in ("/", "/students", "/courses", "/enrollments", "/reports/student", "/reports/course")))
