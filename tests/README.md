# Automated tests

These scripts test the app end to end through Flask's test client against a **local** database
(they always connect to 127.0.0.1, never to AWS). Each one needs a freshly loaded schema.

One-time setup (local MySQL or MariaDB):

    mysql -u root -e "CREATE USER 'tester'@'127.0.0.1' IDENTIFIED BY 'pw'; GRANT ALL ON *.* TO 'tester'@'127.0.0.1';"

Run each test from the project root (reloading the schema first):

    mysql -u root -e "DROP DATABASE IF EXISTS student_db" && mysql -u root < schema.sql && python tests/test_security_and_audit.py
    mysql -u root -e "DROP DATABASE IF EXISTS student_db" && mysql -u root < schema.sql && python tests/test_ai_insights.py
    mysql -u root -e "DROP DATABASE IF EXISTS student_db" && mysql -u root < schema.sql && python tests/test_ui.py
    mysql -u root -e "DROP DATABASE IF EXISTS student_db" && mysql -u root < schema.sql && python tests/test_demo_data.py

Every line starts with PASS or FAIL. The AI tests use a small mock of the Gemini/Groq API, so they need no API key.
