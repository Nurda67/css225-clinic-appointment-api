import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Optional local PostgreSQL client libraries for the pure-Python psycopg driver.
postgres_bin = os.getenv("POSTGRES_BIN")
if postgres_bin:
    os.environ["PATH"] = postgres_bin + os.pathsep + os.environ.get("PATH", "")
