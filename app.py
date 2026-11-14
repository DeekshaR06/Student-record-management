import csv
import io
import json
import os
import re
import secrets
from datetime import timedelta
from functools import wraps

import pymysql
from dotenv import load_dotenv
from flask import (Flask, Response, abort, flash, has_request_context, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import ai_insights

load_dotenv()
app = Flask(__name__)

_key = os.getenv("SECRET_KEY", "")
if len(_key) < 32 or _key.startswith("change"):
    raise RuntimeError("SECRET_KEY in .env must be a random string of at least 32 characters.")
app.secret_key = _key
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=2))

DUMMY_HASH = generate_password_hash("not-a-real-password")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
MAX_FAILED_LOGINS = 5
AI_USER_HOURLY_LIMIT = int(os.getenv("AI_USER_HOURLY_LIMIT", "5"))
AI_DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "20"))  # protects the free-tier quota
AI_CACHE_DAYS = int(os.getenv("AI_CACHE_DAYS", "30"))


# ---------- Database helper ----------
def query(sql, args=(), one=False):
    conn = pymysql.connect(
        host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME", "student_db"),
        cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            head = sql.lstrip().upper()
            if head.startswith("SELECT"):
                return cur.fetchone() if one else cur.fetchall()
            if head.startswith("INSERT"):
                return cur.lastrowid
    finally:
        conn.close()


def csv_response(filename, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------- Audit logging ----------
def client_ip():
    if not has_request_context():
        return None
    return request.headers.get("X-Real-IP") or request.remote_addr


def audit(action, entity=None, entity_id=None, details=None, username=None):
    if has_request_context():
        uid, uname = session.get("user_id"), username or session.get("username")
    else:
        uid, uname = None, username or "system"
    query("INSERT INTO audit_log (user_id, username, action, entity, entity_id, details, ip_address) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s)",
          (uid, (uname or "")[:50] or None, action, entity, entity_id,
           json.dumps(details, default=str) if details else None, client_ip()))


def diff(old, new):
    changes = {}
    for key, value in new.items():
        before = old.get(key)
        if str(before if before is not None else "") != str(value if value is not None else ""):
            changes[key] = {"from": before, "to": value}
    return changes


# ---------- Users ----------
def create_user(username, password, role):
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3-30 characters: letters, digits, . _ -")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if role not in ("admin", "viewer"):
        raise ValueError("Role must be admin or viewer.")
    try:
        uid = query("INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)",
                    (username, generate_password_hash(password), role))
    except pymysql.err.IntegrityError:
        raise ValueError("That username already exists.")
    audit("CREATE", "user", uid, {"username": username, "role": role})
    return uid


# ---------- Security: sessions, CSRF, roles, headers ----------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.context_processor
def inject_globals():
    return dict(csrf_token=csrf_token, current_user=session.get("username"),
                is_admin=session.get("role") == "admin")


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


@app.before_request
def guard():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token.encode(), session.get("csrf", "").encode()):
            abort(400)
    if request.endpoint in (None, "login", "static"):
        return None
    if "user_id" in session:
        u = query("SELECT user_id, username, role FROM users WHERE user_id=%s",
                  (session["user_id"],), one=True)
        if u:
            session["username"], session["role"] = u["username"], u["role"]
            return None
        session.clear()
    return redirect(url_for("login", next=request.full_path.rstrip("?")))


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def error_page(e):
    msgs = {400: "Bad request or expired form. Go back, refresh the page and try again.",
            403: "You do not have permission to do that.", 404: "Page not found."}
    return render_template("error.html", code=e.code, msg=msgs.get(e.code, "Error")), e.code


# ---------- Login / logout / password ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        failed = query("SELECT COUNT(*) AS n FROM audit_log WHERE action='LOGIN_FAILED' "
                       "AND (username=%s OR ip_address=%s) "
                       "AND created_at > NOW() - INTERVAL 10 MINUTE",
                       (username[:50], client_ip()), one=True)["n"]
        if failed >= MAX_FAILED_LOGINS:
            audit("LOGIN_BLOCKED", username=username)
            flash("Too many failed attempts. Please try again in 10 minutes.")
            return render_template("login.html"), 429
        user = query("SELECT * FROM users WHERE username=%s", (username,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.permanent = True
            session.update(user_id=user["user_id"], username=user["username"], role=user["role"])
            audit("LOGIN")
            nxt = request.args.get("next", "")
            if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
                nxt = url_for("dashboard")
            return redirect(nxt)
        if not user:
            check_password_hash(DUMMY_HASH, password)  # keep timing similar
        audit("LOGIN_FAILED", username=username)
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    audit("LOGOUT")
    session.clear()
    return redirect(url_for("login"))


@app.route("/account/password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        f = request.form
        user = query("SELECT * FROM users WHERE user_id=%s", (session["user_id"],), one=True)
        if not check_password_hash(user["password_hash"], f.get("current", "")):
            flash("Current password is incorrect.")
        elif len(f.get("new", "")) < 8:
            flash("New password must be at least 8 characters.")
        elif f.get("new") != f.get("confirm"):
            flash("New passwords do not match.")
        else:
            query("UPDATE users SET password_hash=%s WHERE user_id=%s",
                  (generate_password_hash(f["new"]), user["user_id"]))
            audit("UPDATE", "user", user["user_id"], {"password": "changed"})
            flash("Password changed.")
            return redirect(url_for("dashboard"))
    return render_template("password.html")


# ---------- Dashboard ----------
@app.route("/")
def dashboard():
    counts = query("SELECT (SELECT COUNT(*) FROM students) AS students, "
                   "(SELECT COUNT(*) FROM courses) AS courses, "
                   "(SELECT COUNT(*) FROM enrollments) AS enrollments", one=True)
    popular = query("SELECT c.course_code, c.course_name, COUNT(e.enrollment_id) AS total "
                    "FROM courses c LEFT JOIN enrollments e ON e.course_id = c.course_id "
                    "GROUP BY c.course_id, c.course_code, c.course_name "
                    "ORDER BY total DESC, c.course_code")
    idle = query("SELECT s.student_id, s.first_name, s.last_name FROM students s "
                 "LEFT JOIN enrollments e ON e.student_id = s.student_id "
                 "WHERE e.enrollment_id IS NULL ORDER BY s.student_id")
    return render_template("dashboard.html", counts=counts, popular=popular, idle=idle)


# ---------- Students ----------
STUDENT_FIELDS = ("first_name", "last_name", "email", "phone", "date_of_birth")


def student_data(f):
    data = {k: (f.get(k, "").strip() or None) for k in STUDENT_FIELDS}
    return data


@app.route("/students")
def students():
    q = request.args.get("q", "").strip()
    if q:
        like = f"%{q}%"
        rows = query("SELECT * FROM students WHERE CAST(student_id AS CHAR)=%s OR first_name LIKE %s "
                     "OR last_name LIKE %s OR CONCAT(first_name, ' ', last_name) LIKE %s "
                     "OR email LIKE %s ORDER BY student_id", (q, like, like, like, like))
    else:
        rows = query("SELECT * FROM students ORDER BY student_id")
    return render_template("students.html", rows=rows, q=q)


@app.route("/students/add", methods=["GET", "POST"])
@admin_required
def add_student():
    if request.method == "POST":
        d = student_data(request.form)
        try:
            sid = query("INSERT INTO students (first_name,last_name,email,phone,date_of_birth) "
                        "VALUES (%s,%s,%s,%s,%s)", tuple(d[k] for k in STUDENT_FIELDS))
            audit("CREATE", "student", sid, d)
            flash("Student added.")
            return redirect(url_for("students"))
        except pymysql.err.IntegrityError:
            flash("A student with that email already exists.")
    return render_template("student_form.html", s=request.form, title="Add Student")


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
@admin_required
def edit_student(sid):
    s = query("SELECT * FROM students WHERE student_id=%s", (sid,), one=True)
    if not s:
        abort(404)
    if request.method == "POST":
        d = student_data(request.form)
        try:
            query("UPDATE students SET first_name=%s,last_name=%s,email=%s,phone=%s,date_of_birth=%s "
                  "WHERE student_id=%s", tuple(d[k] for k in STUDENT_FIELDS) + (sid,))
            changes = diff(s, d)
            if changes:
                audit("UPDATE", "student", sid, changes)
            flash("Student updated." if changes else "No changes made.")
            return redirect(url_for("students"))
        except pymysql.err.IntegrityError:
            flash("That email is already used by another student.")
        s = request.form
    return render_template("student_form.html", s=s, title="Edit Student")


@app.route("/students/<int:sid>/delete", methods=["POST"])
@admin_required
def delete_student(sid):
    s = query("SELECT * FROM students WHERE student_id=%s", (sid,), one=True)
    if not s:
        abort(404)
    n = query("SELECT COUNT(*) AS n FROM enrollments WHERE student_id=%s", (sid,), one=True)["n"]
    if n:
        flash(f"Cannot delete: this student is enrolled in {n} course(s). Remove the enrollments first.")
    else:
        try:
            query("DELETE FROM students WHERE student_id=%s", (sid,))
            audit("DELETE", "student", sid, s)
            flash("Student deleted.")
        except pymysql.err.IntegrityError:
            flash("Cannot delete: this student is still referenced by other records.")
    return redirect(url_for("students"))


# ---------- Courses ----------
@app.route("/courses", methods=["GET", "POST"])
def courses():
    if request.method == "POST":
        if session.get("role") != "admin":
            abort(403)
        f = request.form
        d = {"course_code": f["course_code"].strip(), "course_name": f["course_name"].strip(),
             "credits": f["credits"]}
        try:
            cid = query("INSERT INTO courses (course_code,course_name,credits) VALUES (%s,%s,%s)",
                        (d["course_code"], d["course_name"], d["credits"]))
            audit("CREATE", "course", cid, d)
            flash("Course added.")
        except pymysql.err.IntegrityError:
            flash("Course code already exists.")
        return redirect(url_for("courses"))
    return render_template("courses.html", rows=query("SELECT * FROM courses ORDER BY course_id"))


@app.route("/courses/<int:cid>/delete", methods=["POST"])
@admin_required
def delete_course(cid):
    c = query("SELECT * FROM courses WHERE course_id=%s", (cid,), one=True)
    if not c:
        abort(404)
    n = query("SELECT COUNT(*) AS n FROM enrollments WHERE course_id=%s", (cid,), one=True)["n"]
    if n:
        flash(f"Cannot delete: {n} student(s) are enrolled in this course. Remove those enrollments first.")
    else:
        try:
            query("DELETE FROM courses WHERE course_id=%s", (cid,))
            audit("DELETE", "course", cid, c)
            flash("Course deleted.")
        except pymysql.err.IntegrityError:
            flash("Cannot delete: this course is still referenced by other records.")
    return redirect(url_for("courses"))


# ---------- Enrollments ----------
@app.route("/enrollments", methods=["GET", "POST"])
def enrollments():
    if request.method == "POST":
        if session.get("role") != "admin":
            abort(403)
        f = request.form
        grade = f.get("grade", "").strip() or None
        try:
            eid = query("INSERT INTO enrollments (student_id,course_id,grade) VALUES (%s,%s,%s)",
                        (f["student_id"], f["course_id"], grade))
            audit("CREATE", "enrollment", eid,
                  {"student_id": f["student_id"], "course_id": f["course_id"], "grade": grade})
            flash("Student enrolled.")
        except pymysql.err.IntegrityError:
            flash("Student is already enrolled in that course.")
        return redirect(url_for("enrollments"))
    rows = query("SELECT e.enrollment_id, s.first_name, s.last_name, c.course_code, c.course_name, "
                 "e.enrollment_date, e.grade FROM enrollments e "
                 "JOIN students s ON s.student_id = e.student_id "
                 "JOIN courses c ON c.course_id = e.course_id ORDER BY e.enrollment_id")
    return render_template("enrollments.html", rows=rows,
                           students=query("SELECT student_id, first_name, last_name FROM students"),
                           courses=query("SELECT course_id, course_code, course_name FROM courses"))


@app.route("/enrollments/<int:eid>/grade", methods=["POST"])
@admin_required
def update_grade(eid):
    e = query("SELECT * FROM enrollments WHERE enrollment_id=%s", (eid,), one=True)
    if not e:
        abort(404)
    grade = request.form.get("grade", "").strip() or None
    try:
        query("UPDATE enrollments SET grade=%s WHERE enrollment_id=%s", (grade, eid))
        changes = diff(e, {"grade": grade})
        if changes:
            audit("UPDATE", "enrollment", eid, changes)
        flash("Grade updated.")
    except pymysql.err.DataError:
        flash("Grade can be at most 2 characters.")
    return redirect(url_for("enrollments"))


@app.route("/enrollments/<int:eid>/delete", methods=["POST"])
@admin_required
def delete_enrollment(eid):
    e = query("SELECT * FROM enrollments WHERE enrollment_id=%s", (eid,), one=True)
    if not e:
        abort(404)
    query("DELETE FROM enrollments WHERE enrollment_id=%s", (eid,))
    audit("DELETE", "enrollment", eid, e)
    flash("Enrollment removed.")
    return redirect(url_for("enrollments"))


# ---------- AI course insights ----------
def ai_attempts(hours, user_id=None):
    """Counts AI requests (successful or failed) so limits protect the free quota."""
    sql = ("SELECT COUNT(*) AS n FROM audit_log WHERE action IN ('AI_INSIGHT','AI_FAILED') "
           "AND created_at > NOW() - INTERVAL %s HOUR")
    args = [hours]
    if user_id is not None:
        sql += " AND user_id=%s"
        args.append(user_id)
    return query(sql, tuple(args), one=True)["n"]


def safe_sources(raw):
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    return [s for s in items if str(s.get("url", "")).startswith(("https://", "http://"))]


def store_insight(cid, r):
    """Saves (or replaces) the cached AI insight for a course."""
    query("INSERT INTO course_insights (course_id, insight, sources, model, grounded) "
          "VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE insight=VALUES(insight), "
          "sources=VALUES(sources), model=VALUES(model), grounded=VALUES(grounded), "
          "generated_at=CURRENT_TIMESTAMP",
          (cid, r["text"], json.dumps(r["sources"]), r["model"], int(r["grounded"])))


@app.route("/courses/<int:cid>/insights", methods=["GET", "POST"])
def course_insights(cid):
    course = query("SELECT * FROM courses WHERE course_id=%s", (cid,), one=True)
    if not course:
        abort(404)
    cached = query("SELECT *, TIMESTAMPDIFF(DAY, generated_at, NOW()) AS age_days "
                   "FROM course_insights WHERE course_id=%s", (cid,), one=True)
    if request.method == "POST":
        force = request.form.get("refresh") == "1" and session.get("role") == "admin"
        if cached and cached["age_days"] < AI_CACHE_DAYS and not force:
            flash("Insights are already up to date.")
        elif ai_attempts(1, session["user_id"]) >= AI_USER_HOURLY_LIMIT:
            flash(f"You have reached the limit of {AI_USER_HOURLY_LIMIT} AI requests per hour. Please try later.")
        elif ai_attempts(24) >= AI_DAILY_LIMIT:
            flash("The daily AI request limit has been reached. Please try again tomorrow.")
        else:
            try:
                r = ai_insights.generate_insight(course["course_name"])
                store_insight(cid, r)
                audit("AI_INSIGHT", "course", cid, {"model": r["model"], "web_search": r["grounded"]})
                flash("AI insights generated.")
            except ai_insights.AIError as e:
                audit("AI_FAILED", "course", cid, {"reason": str(e)})
                flash(str(e))
        return redirect(url_for("course_insights", cid=cid))
    sections = ai_insights.parse_sections(cached["insight"]) if cached else []
    return render_template("course_insights.html", course=course, insight=cached, sections=sections,
                           sources=safe_sources(cached["sources"]) if cached else [])


# ---------- Reports ----------
@app.route("/reports/student")
def report_student():
    sid = request.args.get("student_id", "").strip()
    student, rows = None, []
    if sid:
        if sid.isdigit():
            student = query("SELECT * FROM students WHERE student_id=%s", (sid,), one=True)
        if student:
            rows = query("SELECT c.course_code, c.course_name, c.credits, e.enrollment_date, e.grade "
                         "FROM enrollments e JOIN courses c ON c.course_id = e.course_id "
                         "WHERE e.student_id=%s ORDER BY c.course_code", (sid,))
        else:
            flash("No student found with that ID.")
    if student and request.args.get("format") == "csv":
        return csv_response(f"student_{sid}_courses.csv",
                            ["Course code", "Course name", "Credits", "Enrolled on", "Grade"],
                            [list(r.values()) for r in rows])
    return render_template("report_student.html", sid=sid, student=student, rows=rows)


@app.route("/reports/course")
def report_course():
    cid = request.args.get("course_id", "").strip()
    all_courses = query("SELECT course_id, course_code, course_name FROM courses ORDER BY course_code")
    course, rows = None, []
    if cid.isdigit():
        course = query("SELECT * FROM courses WHERE course_id=%s", (cid,), one=True)
        if course:
            rows = query("SELECT s.student_id, s.first_name, s.last_name, s.email, e.enrollment_date, e.grade "
                         "FROM enrollments e JOIN students s ON s.student_id = e.student_id "
                         "WHERE e.course_id=%s ORDER BY s.first_name, s.last_name", (cid,))
    if course and request.args.get("format") == "csv":
        return csv_response(f"course_{course['course_code']}_students.csv",
                            ["Student ID", "First name", "Last name", "Email", "Enrolled on", "Grade"],
                            [list(r.values()) for r in rows])
    return render_template("report_course.html", cid=cid, courses=all_courses, course=course, rows=rows)


# ---------- Admin: users and audit report ----------
@app.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        f = request.form
        try:
            create_user(f.get("username", "").strip(), f.get("password", ""), f.get("role", ""))
            flash("User created.")
        except ValueError as e:
            flash(str(e))
        return redirect(url_for("users"))
    rows = query("SELECT user_id, username, role, created_at FROM users ORDER BY user_id")
    return render_template("users.html", rows=rows)


@app.route("/users/<int:uid>/delete", methods=["POST"])
@admin_required
def delete_user(uid):
    u = query("SELECT user_id, username, role FROM users WHERE user_id=%s", (uid,), one=True)
    if not u:
        abort(404)
    if uid == session["user_id"]:
        flash("You cannot delete your own account.")
    else:
        query("DELETE FROM users WHERE user_id=%s", (uid,))
        audit("DELETE", "user", uid, {"username": u["username"], "role": u["role"]})
        flash("User deleted.")
    return redirect(url_for("users"))


ACTIONS = ("CREATE", "UPDATE", "DELETE", "LOGIN", "LOGOUT", "LOGIN_FAILED", "LOGIN_BLOCKED",
           "AI_INSIGHT", "AI_FAILED")
ENTITIES = ("student", "course", "enrollment", "user", "demo_data")


@app.route("/audit")
@admin_required
def audit_report():
    where, args = [], []
    for field in ("username", "action", "entity"):
        value = request.args.get(field, "").strip()
        if value:
            where.append(f"{field}=%s")
            args.append(value)
    sql = "SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "") + \
          " ORDER BY log_id DESC LIMIT 500"
    rows = query(sql, tuple(args))
    if request.args.get("format") == "csv":
        return csv_response("audit_log.csv",
                            ["Time (UTC)", "User", "Action", "Entity", "Entity ID", "Details", "IP"],
                            [[r["created_at"], r["username"], r["action"], r["entity"], r["entity_id"],
                              r["details"], r["ip_address"]] for r in rows])
    return render_template("audit.html", rows=rows, actions=ACTIONS, entities=ENTITIES,
                           f={k: request.args.get(k, "") for k in ("username", "action", "entity")})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
