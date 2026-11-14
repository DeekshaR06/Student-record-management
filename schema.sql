-- Student Record Management System: MySQL schema (3NF)
CREATE DATABASE IF NOT EXISTS student_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE student_db;

-- 1. Students
CREATE TABLE students (
    student_id    INT AUTO_INCREMENT PRIMARY KEY,
    first_name    VARCHAR(50)  NOT NULL,
    last_name     VARCHAR(50)  NOT NULL,
    email         VARCHAR(100) NOT NULL UNIQUE,
    phone         VARCHAR(15),
    date_of_birth DATE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 2. Courses
CREATE TABLE courses (
    course_id   INT AUTO_INCREMENT PRIMARY KEY,
    course_code VARCHAR(10)  NOT NULL UNIQUE,
    course_name VARCHAR(100) NOT NULL,
    credits     TINYINT      NOT NULL CHECK (credits BETWEEN 1 AND 10),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 3. Enrollments (resolves the many-to-many between students and courses)
CREATE TABLE enrollments (
    enrollment_id   INT AUTO_INCREMENT PRIMARY KEY,
    student_id      INT NOT NULL,
    course_id       INT NOT NULL,
    enrollment_date DATE NOT NULL DEFAULT (CURRENT_DATE),
    grade           CHAR(2),
    CONSTRAINT fk_enr_student FOREIGN KEY (student_id)
        REFERENCES students(student_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_enr_course FOREIGN KEY (course_id)
        REFERENCES courses(course_id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT uq_student_course UNIQUE (student_id, course_id)
) ENGINE=InnoDB;

-- 4. Users and audit log (login, roles, change tracking)
CREATE TABLE IF NOT EXISTS users (
    user_id       INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(30)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('admin','viewer') NOT NULL DEFAULT 'viewer',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- No foreign key to users on purpose: audit history must survive user deletion
CREATE TABLE IF NOT EXISTS audit_log (
    log_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NULL,
    username   VARCHAR(50),
    action     VARCHAR(20) NOT NULL,
    entity     VARCHAR(20),
    entity_id  INT,
    details    TEXT,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_audit_time (created_at),
    INDEX idx_audit_user (username),
    INDEX idx_audit_action (action)
) ENGINE=InnoDB;

-- 5. Cached AI course insights
CREATE TABLE IF NOT EXISTS course_insights (
    course_id    INT PRIMARY KEY,
    insight      TEXT NOT NULL,
    sources      TEXT,
    model        VARCHAR(60),
    grounded     TINYINT(1) NOT NULL DEFAULT 0,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_insight_course FOREIGN KEY (course_id)
        REFERENCES courses(course_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Sample data
INSERT INTO students (first_name, last_name, email, phone, date_of_birth) VALUES
('Asha',  'Rao',    'asha.rao@example.com',  '9876543210', '2003-04-12'),
('Rahul', 'Sharma', 'rahul.s@example.com',   '9123456780', '2002-11-30'),
('Meena', 'Iyer',   'meena.iyer@example.com','9988776655', '2003-07-21');

INSERT INTO courses (course_code, course_name, credits) VALUES
('CS101', 'Introduction to Programming', 4),
('CS201', 'Database Management Systems', 4),
('CS301', 'Cloud Computing', 3);

INSERT INTO enrollments (student_id, course_id, grade) VALUES
(1, 1, 'A'), (1, 2, 'B+'), (2, 2, 'A'), (3, 3, NULL);
