"""Generate a new private lab .env without displaying its password."""

import os
import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".env"
password = secrets.token_urlsafe(32)
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; preserving it. No credentials changed.")
with os.fdopen(descriptor, "w") as stream:
    stream.write("DB_HOST=postgres\nDB_NAME=storex\nDB_USER=storex_user\nDB_PASS=" + password + "\n")
print("Created private .env with generated local password (mode 0600); password not displayed.")
