-- Run once on the existing database: adds login users and the audit log
USE student_db;
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
