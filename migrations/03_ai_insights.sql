-- Run once on the existing database: cache table for AI course insights
USE student_db;
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
