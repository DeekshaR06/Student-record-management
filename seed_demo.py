"""Load fictional demo data so searches and reports have something to show.

Run on the server (inside the venv, in the app folder):   python seed_demo.py

Safe to run more than once: it only adds what is missing (matching students by email,
courses by code, enrollments by student + course) and never changes or deletes anything.
All names are fictional; emails use example.com and phone numbers are obviously fake.
"""
from datetime import date, timedelta

from app import audit, query

STUDENTS = [  # first, last, email, phone, date of birth
    ("Ananya", "Krishnan", "ananya.krishnan@example.com", "9000000001", "2003-02-14"),
    ("Rohan", "Mehta", "rohan.mehta@example.com", "9000000002", "2002-09-03"),
    ("Priya", "Nair", "priya.nair@example.com", "9000000003", "2003-06-21"),
    ("Karthik", "Reddy", "karthik.reddy@example.com", "9000000004", "2002-12-11"),
    ("Sneha", "Patil", "sneha.patil@example.com", "9000000005", "2003-04-27"),
    ("Arjun", "Verma", "arjun.verma@example.com", "9000000006", "2002-08-19"),
    ("Divya", "Menon", "divya.menon@example.com", "9000000007", "2003-11-05"),
    ("Vikram", "Singh", "vikram.singh@example.com", "9000000008", "2002-05-30"),
    ("Lakshmi", "Iyer", "lakshmi.iyer@example.com", "9000000009", "2003-01-17"),
    ("Sanjay", "Gowda", "sanjay.gowda@example.com", "9000000010", "2002-10-08"),
    ("Neha", "Kapoor", "neha.kapoor@example.com", "9000000011", "2003-07-24"),
    ("Farhan", "Sheikh", "farhan.sheikh@example.com", "9000000012", "2002-03-12"),  # left unenrolled on purpose
]

COURSES = [  # code, name, credits
    ("CS101", "Introduction to Programming", 4),
    ("CS102", "Data Structures and Algorithms", 4),
    ("CS201", "Database Management Systems", 4),
    ("CS202", "Operating Systems", 4),
    ("CS203", "Computer Networks", 3),
    ("CS204", "Web Technologies", 3),
    ("CS301", "Cloud Computing", 3),
    ("CS302", "Software Engineering", 3),
    ("CS303", "Machine Learning", 4),
    ("CS304", "Cyber Security", 3),
    ("CS305", "DevOps and CI/CD", 3),
    ("CS401", "Artificial Intelligence", 4),
]

ENROLLMENTS = [  # student email, course code, grade
    ("asha.rao@example.com", "CS102", "A"), ("asha.rao@example.com", "CS301", "B+"),
    ("rahul.s@example.com", "CS101", "B"), ("rahul.s@example.com", "CS202", "B+"),
    ("meena.iyer@example.com", "CS301", "A"),
    ("ananya.krishnan@example.com", "CS101", "A+"), ("ananya.krishnan@example.com", "CS102", "A"),
    ("ananya.krishnan@example.com", "CS201", "A"), ("ananya.krishnan@example.com", "CS301", "B+"),
    ("rohan.mehta@example.com", "CS101", "B+"), ("rohan.mehta@example.com", "CS201", "B"),
    ("rohan.mehta@example.com", "CS203", "B"), ("rohan.mehta@example.com", "CS304", None),
    ("priya.nair@example.com", "CS102", "A"), ("priya.nair@example.com", "CS201", "A+"),
    ("priya.nair@example.com", "CS303", "A"), ("priya.nair@example.com", "CS301", "A"),
    ("karthik.reddy@example.com", "CS202", "B"), ("karthik.reddy@example.com", "CS203", "B+"),
    ("karthik.reddy@example.com", "CS302", "B"), ("karthik.reddy@example.com", "CS305", None),
    ("sneha.patil@example.com", "CS201", "B+"), ("sneha.patil@example.com", "CS204", "A"),
    ("sneha.patil@example.com", "CS301", "B"),
    ("arjun.verma@example.com", "CS101", "C"), ("arjun.verma@example.com", "CS102", "B"),
    ("arjun.verma@example.com", "CS202", "B+"),
    ("divya.menon@example.com", "CS204", "A"), ("divya.menon@example.com", "CS303", "A+"),
    ("divya.menon@example.com", "CS401", "A"), ("divya.menon@example.com", "CS201", "A"),
    ("vikram.singh@example.com", "CS203", "B"), ("vikram.singh@example.com", "CS304", "A"),
    ("vikram.singh@example.com", "CS305", "B+"), ("vikram.singh@example.com", "CS301", "B+"),
    ("lakshmi.iyer@example.com", "CS302", "A"), ("lakshmi.iyer@example.com", "CS201", "B+"),
    ("lakshmi.iyer@example.com", "CS301", "A"), ("lakshmi.iyer@example.com", "CS401", None),
    ("sanjay.gowda@example.com", "CS102", "B+"), ("sanjay.gowda@example.com", "CS202", "A"),
    ("sanjay.gowda@example.com", "CS303", "B+"),
    ("neha.kapoor@example.com", "CS204", "B+"), ("neha.kapoor@example.com", "CS304", "A"),
    ("neha.kapoor@example.com", "CS401", "B"), ("neha.kapoor@example.com", "CS301", "A"),
]


def main():
    added = {"students": 0, "courses": 0, "enrollments": 0}
    skipped = 0

    for first, last, email, phone, dob in STUDENTS:
        if not query("SELECT 1 AS x FROM students WHERE email=%s", (email,), one=True):
            query("INSERT INTO students (first_name,last_name,email,phone,date_of_birth) VALUES (%s,%s,%s,%s,%s)",
                  (first, last, email, phone, dob))
            added["students"] += 1

    for code, name, credits in COURSES:
        if not query("SELECT 1 AS x FROM courses WHERE course_code=%s", (code,), one=True):
            query("INSERT INTO courses (course_code,course_name,credits) VALUES (%s,%s,%s)", (code, name, credits))
            added["courses"] += 1

    start = date(2026, 8, 10)
    for i, (email, code, grade) in enumerate(ENROLLMENTS):
        s = query("SELECT student_id FROM students WHERE email=%s", (email,), one=True)
        c = query("SELECT course_id FROM courses WHERE course_code=%s", (code,), one=True)
        if not s or not c:  # e.g. a sample student was deleted earlier
            skipped += 1
            continue
        if query("SELECT 1 AS x FROM enrollments WHERE student_id=%s AND course_id=%s",
                 (s["student_id"], c["course_id"]), one=True):
            continue
        query("INSERT INTO enrollments (student_id,course_id,enrollment_date,grade) VALUES (%s,%s,%s,%s)",
              (s["student_id"], c["course_id"], start + timedelta(days=(i * 5) % 35), grade))
        added["enrollments"] += 1

    if any(added.values()):
        audit("CREATE", "demo_data", None, {**added, "note": "fictional demo data loaded by seed_demo.py"})
        print(f"Added {added['students']} students, {added['courses']} courses and "
              f"{added['enrollments']} enrollments.")
    else:
        print("Nothing to add: the demo data is already there.")
    if skipped:
        print(f"Skipped {skipped} enrollments because a referenced student or course does not exist.")
    totals = query("SELECT (SELECT COUNT(*) FROM students) AS s, (SELECT COUNT(*) FROM courses) AS c, "
                   "(SELECT COUNT(*) FROM enrollments) AS e", one=True)
    print(f"Database now has {totals['s']} students, {totals['c']} courses, {totals['e']} enrollments.")


if __name__ == "__main__":
    main()
