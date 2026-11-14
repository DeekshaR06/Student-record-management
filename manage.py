"""Create login users from the command line.

Usage:  python manage.py create-user USERNAME [--role admin|viewer]
The password is typed at a hidden prompt and is never stored in code or logs.
"""
import argparse
import getpass
import sys

from app import create_user

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["create-user"])
parser.add_argument("username")
parser.add_argument("--role", choices=["admin", "viewer"], default="admin")
args = parser.parse_args()

password = getpass.getpass("Password (min 8 characters): ")
if password != getpass.getpass("Confirm password: "):
    sys.exit("Passwords do not match.")
try:
    create_user(args.username, password, args.role)
    print(f"Created {args.role} user '{args.username}'.")
except ValueError as e:
    sys.exit(f"Error: {e}")
