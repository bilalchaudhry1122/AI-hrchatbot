#!/usr/bin/env bash
# Install or update the HR bot on Ubuntu/Debian.
#
#   tar xzf hr-bot-bundle.tar.gz && cd hr-bot-bundle && sudo bash deploy/install.sh
#
# First run: installs Python/MySQL if missing, creates the `hrbot` user, a
# separate `webairy_hr` database + `hrbot` MySQL user, imports hr.sql, and
# starts the `hr-bot` systemd service.
# Later runs: update the code only; .env, the database and ticket state are kept.
set -euo pipefail

APP_DIR=/opt/hr-bot
SERVICE=hr-bot
DB_NAME=webairy_hr
DB_USER=hrbot
SRC="$(cd "$(dirname "$0")/.." && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash deploy/install.sh"; exit 1; }

FIRST_INSTALL=1
[ -f "$APP_DIR/.installed" ] && FIRST_INSTALL=0

echo "==> System packages"
export DEBIAN_FRONTEND=noninteractive
if command -v curl >/dev/null 2>&1 && command -v openssl >/dev/null 2>&1 \
    && python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
    echo "   already present; skipping apt"
else
    # A broken third-party repo (e.g. an expired MySQL apt key) must not stop the install.
    apt-get update -qq || echo "   (apt update reported errors from another repository; continuing)"
    apt-get install -y -qq python3 python3-venv curl ca-certificates openssl >/dev/null
fi
if ! command -v mysql >/dev/null 2>&1; then
    echo "==> Installing MySQL server"
    apt-get install -y -qq mysql-server >/dev/null
fi
systemctl enable --now mysql >/dev/null 2>&1 || systemctl enable --now mariadb >/dev/null 2>&1 || true

echo "==> App user and files"
id -u hrbot >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin hrbot
mkdir -p "$APP_DIR"
if systemctl is-active --quiet "$SERVICE"; then systemctl stop "$SERVICE"; fi
rm -rf "$APP_DIR/app" "$APP_DIR/scripts"
cp -a "$SRC/app" "$SRC/scripts" "$SRC/requirements.txt" "$SRC/pyproject.toml" "$APP_DIR/"
find "$APP_DIR/app" "$APP_DIR/scripts" -name "__pycache__" -type d -prune -exec rm -rf {} +

if [ "$FIRST_INSTALL" -eq 1 ]; then
    cp -a "$SRC/.env" "$SRC/channels.json" "$APP_DIR/"
    for f in tickets.json sessions.json leave_drafts.json; do
        [ -f "$SRC/$f" ] && cp -a "$SRC/$f" "$APP_DIR/"
    done

    echo "==> Database $DB_NAME (user $DB_USER)"
    if mysql -N -e "SHOW DATABASES LIKE '$DB_NAME'" | grep -q "$DB_NAME"; then
        echo "Database $DB_NAME already exists on this server. Refusing to overwrite it."
        echo "Drop it yourself if it is leftover: sudo mysql -e 'DROP DATABASE $DB_NAME'"
        exit 1
    fi
    # Upper, lower, digit and "_" so MySQL password policies accept it; still URL-safe.
    DB_PASS="Hb_$(openssl rand -hex 20)_Q7"
    mysql <<SQL
CREATE DATABASE $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
    # MariaDB does not know MySQL 8's default collation; unicode_ci works on both.
    sed 's/utf8mb4_0900_ai_ci/utf8mb4_unicode_ci/g' "$SRC/hr.sql" | mysql "$DB_NAME"
    sed -i "s#^DATABASE_URL=.*#DATABASE_URL=mysql://$DB_USER:$DB_PASS@127.0.0.1:3306/$DB_NAME#" "$APP_DIR/.env"
    touch "$APP_DIR/.installed"
    echo "   imported: $(mysql -N -e "SELECT COUNT(*) FROM $DB_NAME.employees") employees, $(mysql -N -e "SELECT COUNT(*) FROM $DB_NAME.leave_requests") leave requests"
fi

echo "==> Python environment"
if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    [ -x "$APP_DIR/.venv/bin/python" ] || python3 -m venv "$APP_DIR/.venv"
else
    echo "   python3 is older than 3.12; installing Python 3.12 with uv"
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
    [ -x "$APP_DIR/.venv/bin/python" ] || UV_PYTHON_INSTALL_DIR="$APP_DIR/.python" uv venv --seed --python 3.12 "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -q -r "$APP_DIR/requirements.txt"

chown -R hrbot:hrbot "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> Service"
cp "$SRC/deploy/hr-bot.service" /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
systemctl enable --now "$SERVICE" >/dev/null
sleep 20
systemctl --no-pager --lines=0 status "$SERVICE" | head -5
echo
journalctl -u "$SERVICE" --no-pager -n 40 | grep -E "\[(info|warn|error)\]|Traceback|Error" | tail -15
echo
echo "Done. Logs: journalctl -u $SERVICE -f    Restart: sudo systemctl restart $SERVICE"
