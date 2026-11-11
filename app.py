import os
import pymysql
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")


def query(sql, args=(), one=False):
    conn = pymysql.connect(
        host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"), database=os.getenv("DB_NAME", "student_db"),
        cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            if sql.lstrip().upper().startswith("SELECT"):
                return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


@app.route("/")
def index():
    return redirect(url_for("students"))


# ---------- Students (CRUD) ----------
@app.route("/students")
def students():
    return render_template("students.html", rows=query("SELECT * FROM students ORDER BY student_id"))


@app.route("/students/add", methods=["GET", "POST"])
def add_student():
    if request.method == "POST":
        f = request.form
        try:
            query("INSERT INTO students (first_name,last_name,email,phone,date_of_birth) "
                  "VALUES (%s,%s,%s,%s,%s)",
                  (f["first_name"], f["last_name"], f["email"], f["phone"] or None, f["date_of_birth"] or None))
            flash("Student added.")
            return redirect(url_for("students"))
        except pymysql.err.IntegrityError:
            flash("A student with that email already exists.")
    return render_template("student_form.html", s=request.form, title="Add Student")


@app.route("/students/<int:sid>/edit", methods=["GET", "POST"])
def edit_student(sid):
    s = query("SELECT * FROM students WHERE student_id=%s", (sid,), one=True)
    if not s:
        abort(404)
    if request.method == "POST":
        f = request.form
        try:
            query("UPDATE students SET first_name=%s,last_name=%s,email=%s,phone=%s,date_of_birth=%s "
                  "WHERE student_id=%s",
                  (f["first_name"], f["last_name"], f["email"], f["phone"] or None,
                   f["date_of_birth"] or None, sid))
            flash("Student updated.")
            return redirect(url_for("students"))
        except pymysql.err.IntegrityError:
            flash("That email is already used by another student.")
        s = f
    return render_template("student_form.html", s=s, title="Edit Student")


@app.route("/students/<int:sid>/delete", methods=["POST"])
def delete_student(sid):
    query("DELETE FROM students WHERE student_id=%s", (sid,))
    flash("Student deleted.")
    return redirect(url_for("students"))


# ---------- Courses ----------
@app.route("/courses", methods=["GET", "POST"])
def courses():
    if request.method == "POST":
        f = request.form
        try:
            query("INSERT INTO courses (course_code,course_name,credits) VALUES (%s,%s,%s)",
                  (f["course_code"], f["course_name"], f["credits"]))
            flash("Course added.")
        except pymysql.err.IntegrityError:
            flash("Course code already exists.")
        return redirect(url_for("courses"))
    return render_template("courses.html", rows=query("SELECT * FROM courses ORDER BY course_id"))


@app.route("/courses/<int:cid>/delete", methods=["POST"])
def delete_course(cid):
    query("DELETE FROM courses WHERE course_id=%s", (cid,))
    flash("Course deleted.")
    return redirect(url_for("courses"))


# ---------- Enrollments ----------
@app.route("/enrollments", methods=["GET", "POST"])
def enrollments():
    if request.method == "POST":
        f = request.form
        try:
            query("INSERT INTO enrollments (student_id,course_id,grade) VALUES (%s,%s,%s)",
                  (f["student_id"], f["course_id"], f["grade"] or None))
            flash("Student enrolled.")
        except pymysql.err.IntegrityError:
            flash("Student is already enrolled in that course.")
        return redirect(url_for("enrollments"))
    rows = query("SELECT e.enrollment_id, s.first_name, s.last_name, c.course_code, c.course_name, "
                 "e.enrollment_date, e.grade FROM enrollments e "
                 "JOIN students s USING(student_id) JOIN courses c USING(course_id) "
                 "ORDER BY e.enrollment_id")
    return render_template("enrollments.html", rows=rows,
                           students=query("SELECT student_id, first_name, last_name FROM students"),
                           courses=query("SELECT course_id, course_code, course_name FROM courses"))


@app.route("/enrollments/<int:eid>/delete", methods=["POST"])
def delete_enrollment(eid):
    query("DELETE FROM enrollments WHERE enrollment_id=%s", (eid,))
    flash("Enrollment removed.")
    return redirect(url_for("enrollments"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
