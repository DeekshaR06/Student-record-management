# Student Record Management System

Cloud Computing Assignment 1: a Flask web app that manages student records in a relational database.

**Live demo:** http://15.206.178.255/students

## Architecture
Browser -> Nginx (port 80) -> Gunicorn -> Flask app (EC2, Ubuntu 26.04) -> Amazon RDS MySQL 8.4 (private, port 3306)

- **VM:** AWS EC2 t3.micro, ap-south-1 (Mumbai)
- **Database:** Amazon RDS MySQL 8.4, db.t4g.micro, not publicly accessible; only the EC2 security group can connect
- **Stack:** Python Flask, PyMySQL, Gunicorn, Nginx

## Features
- Students: add, view, update, delete
- Courses: add, view, delete
- Enrollments: enrol a student in a course, view, remove

## Database
`schema.sql` creates `students`, `courses` and `enrollments` (3NF). Enrollments resolves the many-to-many relationship with foreign keys, a unique (student, course) pair, and ON DELETE CASCADE.

## Deployment steps
1. Launch an EC2 Ubuntu instance; security group allows SSH (22, your IP) and HTTP (80).
2. Create an RDS MySQL instance (initial DB name `student_db`, public access No) and connect it to the EC2 instance.
3. On the VM: `sudo apt update && sudo apt install -y nginx python3-venv python3-pip mysql-client unzip`
4. Load the schema: `mysql -h <rds-endpoint> -u admin -p < schema.sql`
5. Copy this project to `/home/ubuntu/student-app`, then:
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env     # then edit .env with the real DB password
   ```
6. Run as a service: copy `deploy/studentapp.service` to `/etc/systemd/system/`, then `sudo systemctl daemon-reload && sudo systemctl enable --now studentapp`
7. Nginx: remove the default site, copy `deploy/nginx-studentapp.conf` to `/etc/nginx/sites-available/studentapp`, symlink it into `sites-enabled`, run `sudo nginx -t`, then `sudo systemctl restart nginx`.

Credentials live in `.env`, which is excluded from the repository.
