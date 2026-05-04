#!/bin/bash
set -e

echo "================================"
echo "  M3 Setup"
echo "  Personal Knowledge OS"
echo "================================"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed."
    echo "Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "Error: Docker Compose is not available."
    exit 1
fi

echo "Docker found."

# Pick a Python interpreter for port probing.
PY=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        PY="$cmd"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Error: python3 is required for port discovery."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
find_port() {
    "$PY" "$SCRIPT_DIR/find_free_port.py" "$1"
}

write_var() {
    # write_var KEY VALUE FILE — replace existing line or append.
    local key="$1" value="$2" file="$3"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
        rm -f "${file}.bak"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

echo ""

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"

    # Prompt for an LLM key -- prefer Claude Code (no key needed) when present,
    # otherwise ask for an Anthropic key.
    if command -v claude &> /dev/null; then
        echo "Detected the 'claude' CLI -- M3 can use it directly (no API key needed)."
        echo "Set M3_LLM__DEFAULT_PROVIDER=local_agent in .env to enable it."
    else
        read -p "Anthropic API key (sk-ant-..., or leave blank): " ANTHROPIC_KEY
        if [ -n "$ANTHROPIC_KEY" ]; then
            write_var ANTHROPIC_API_KEY "$ANTHROPIC_KEY" .env
        fi
    fi

    # Generate M3 API key
    M3_KEY=$(openssl rand -hex 32 2>/dev/null || "$PY" -c "import secrets; print(secrets.token_hex(32))")
    if [ -z "$M3_KEY" ]; then
        echo "Error: failed to generate M3 API key (need openssl or python3)."
        exit 1
    fi
    write_var M3_API_KEY "$M3_KEY" .env
    echo ""
    echo "Your M3 API key: $M3_KEY"
    echo "(Save this -- you'll need it to access the web UI)"
    echo ""

    read -p "Telegram bot token (optional, press Enter to skip): " TG_TOKEN
    if [ -n "$TG_TOKEN" ]; then
        write_var TELEGRAM_BOT_TOKEN "$TG_TOKEN" .env
    fi

    echo ""
else
    echo ".env already exists, skipping initial configuration."
    echo ""
fi

# --- Port discovery -----------------------------------------------------------
# Probe each preferred host-side port; if taken, walk upward. Persist to .env so
# docker-compose picks up the same values on subsequent runs.
echo "Discovering free ports..."
declare -A PORTS=(
    [M3_HTTP_PORT]=80
    [M3_HTTPS_PORT]=443
    [M3_API_PORT]=8000
    [M3_POSTGRES_PORT]=5432
    [M3_REDIS_PORT]=6380
    [M3_MINIO_PORT]=9000
    [M3_MINIO_CONSOLE_PORT]=9001
)
for var in "${!PORTS[@]}"; do
    preferred="${PORTS[$var]}"
    existing=$(grep "^${var}=" .env 2>/dev/null | cut -d= -f2 || true)
    if [ -n "$existing" ]; then
        chosen="$existing"
    else
        chosen=$(find_port "$preferred")
        write_var "$var" "$chosen" .env
    fi
    if [ "$chosen" != "$preferred" ]; then
        echo "  $var: $preferred busy -> using $chosen"
    else
        echo "  $var: $chosen"
    fi
done
echo ""

# Create config.yml if it doesn't exist
if [ ! -f config.yml ]; then
    cp config.example.yml config.yml
    echo "Created config.yml from config.example.yml"

    # Enable Telegram if token was provided
    if grep -q "^TELEGRAM_BOT_TOKEN=." .env; then
        sed -i.bak 's/enabled: false/enabled: true/' config.yml
        rm -f config.yml.bak
        echo "Telegram bot enabled in config."
    fi
    echo ""
fi

# Source .env so docker-compose substitution works in this shell.
set -a
. ./.env
set +a

echo "Starting M3..."
docker compose up -d --build

echo ""
echo "Waiting for services to be healthy..."
sleep 5

API_PORT="${M3_API_PORT:-8000}"
HTTP_PORT="${M3_HTTP_PORT:-80}"
MINIO_CONSOLE="${M3_MINIO_CONSOLE_PORT:-9001}"

if curl -sf "http://localhost:${API_PORT}/api/v1/status" > /dev/null 2>&1; then
    echo ""
    echo "================================"
    echo "  M3 is running!"
    echo "================================"
    echo ""
    echo "  Web UI:  http://localhost:${HTTP_PORT}"
    echo "  API:     http://localhost:${API_PORT}/api/v1/status"
    echo "  MinIO:   http://localhost:${MINIO_CONSOLE}"
    echo ""
    echo "  Enter your API key in Settings to get started."
    echo ""
else
    echo ""
    echo "Services are starting up. Check status with:"
    echo "  docker compose ps"
    echo "  docker compose logs server"
    echo ""
fi
