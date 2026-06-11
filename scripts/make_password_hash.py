"""Generate a password hash for the AUTH_USERS environment variable.

Usage:
    python scripts/make_password_hash.py            # prompts for the password
    python scripts/make_password_hash.py "mypass"   # password as an argument

Output is a werkzeug (scrypt) hash. Put accounts in AUTH_USERS as a
comma- or newline-separated list of "email:hash" entries, e.g.:

    AUTH_USERS="alice@wsu.edu:scrypt:...:...,bob@wsu.edu:scrypt:...:..."

For a single quick account you can instead set AUTH_OWNER_EMAIL and
AUTH_OWNER_PASSWORD (plaintext, hashed in memory at startup).
"""
import getpass
import sys

from werkzeug.security import generate_password_hash


def main() -> None:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm: "):
            print("Passwords did not match.", file=sys.stderr)
            sys.exit(1)
    if not password:
        print("Empty password.", file=sys.stderr)
        sys.exit(1)
    print(generate_password_hash(password))


if __name__ == "__main__":
    main()
