"""Pack the bot for the Linux server: code, settings, ticket state and a MySQL dump.

Stop the bot on this PC first so the dump and state files are final:
    .venv\\Scripts\\python deploy\\make_bundle.py

Output: deploy/out/hr-bot-bundle.tar.gz (contains .env secrets; never commit it).
"""

import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_config  # noqa: E402
from app.process_lock import is_pid_running, lock_path_for  # noqa: E402

MYSQLDUMP = Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe")
BUNDLE = "hr-bot-bundle"
INCLUDE = ["app", "scripts", "requirements.txt", "pyproject.toml", "channels.json", ".env",
           "tickets.json", "sessions.json", "leave_drafts.json",
           "deploy/install.sh", "deploy/hr-bot.service"]
LF_ONLY = {"deploy/install.sh", "deploy/hr-bot.service"}


def main():
    test = "--test" in sys.argv
    lock = lock_path_for(ROOT)
    if not test and lock.exists() and is_pid_running(lock.read_text().strip() or 0):
        sys.exit("The bot is still running on this PC. Stop it first, then run this again.")

    db = load_config()["db"]
    dump = subprocess.run(
        [str(MYSQLDUMP if MYSQLDUMP.exists() else "mysqldump"), "-h", db["host"], "-P", str(db["port"]),
         "-u", db["user"], "--single-transaction", "--no-tablespaces", "--set-gtid-purged=OFF",
         "--default-character-set=utf8mb4", db["name"]],
        capture_output=True,
        env={**os.environ, "MYSQL_PWD": db["password"]},
    )
    if dump.returncode != 0:
        sys.exit("mysqldump failed: " + dump.stderr.decode(errors="replace"))

    out_dir = ROOT / "deploy" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (f"{BUNDLE}-test.tar.gz" if test else f"{BUNDLE}.tar.gz")

    def skip_cache(info):
        return None if "__pycache__" in info.name else info

    def add_bytes(tar, name, data):
        info = tarfile.TarInfo(f"{BUNDLE}/{name}")
        info.size = len(data)
        info.mode = 0o755 if name.endswith(".sh") else 0o644
        tar.addfile(info, io.BytesIO(data))

    with tarfile.open(target, "w:gz") as tar:
        for rel in INCLUDE:
            path = ROOT / rel
            if not path.exists():
                continue
            if rel in LF_ONLY:
                add_bytes(tar, rel, path.read_bytes().replace(b"\r\n", b"\n"))
            else:
                tar.add(path, arcname=f"{BUNDLE}/{rel}", filter=skip_cache)
        add_bytes(tar, "hr.sql", dump.stdout)

    print(f"Bundle ready: {target} ({target.stat().st_size // 1024} KB, database dump {len(dump.stdout) // 1024} KB)")


if __name__ == "__main__":
    main()
