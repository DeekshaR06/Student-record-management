-- Run once on the existing database: block deleting rows that still have enrollments
USE student_db;
ALTER TABLE enrollments DROP FOREIGN KEY fk_enr_student, DROP FOREIGN KEY fk_enr_course;
ALTER TABLE enrollments
  ADD CONSTRAINT fk_enr_student FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  ADD CONSTRAINT fk_enr_course  FOREIGN KEY (course_id)  REFERENCES courses(course_id)  ON DELETE RESTRICT ON UPDATE CASCADE;
