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
echo ""

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
    echo ""

    # Prompt for API key
    read -p "Anthropic API key (sk-ant-...): " ANTHROPIC_KEY
    if [ -n "$ANTHROPIC_KEY" ]; then
        sed -i.bak "s|ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$ANTHROPIC_KEY|" .env
        rm -f .env.bak
    fi

    # Generate M3 API key
    M3_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i.bak "s|M3_API_KEY=.*|M3_API_KEY=$M3_KEY|" .env
    rm -f .env.bak
    echo ""
    echo "Your M3 API key: $M3_KEY"
    echo "(Save this -- you'll need it to access the web UI)"
    echo ""

    # Telegram bot (optional)
    read -p "Telegram bot token (optional, press Enter to skip): " TG_TOKEN
    if [ -n "$TG_TOKEN" ]; then
        sed -i.bak "s|TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TG_TOKEN|" .env
        rm -f .env.bak
    fi

    echo ""
else
    echo ".env already exists, skipping configuration."
    echo ""
fi

# Create config.yml if it doesn't exist
if [ ! -f config.yml ]; then
    cp config.example.yml config.yml
    echo "Created config.yml from config.example.yml"

    # Enable Telegram if token was provided
    if grep -q "TELEGRAM_BOT_TOKEN=." .env; then
        if command -v sed &> /dev/null; then
            sed -i.bak 's/enabled: false/enabled: true/' config.yml
            rm -f config.yml.bak
            echo "Telegram bot enabled in config."
        fi
    fi
    echo ""
fi

# Start services
echo "Starting M3..."
docker compose up -d --build

echo ""
echo "Waiting for services to be healthy..."
sleep 5

# Check health
if curl -sf http://localhost:8000/api/v1/status > /dev/null 2>&1; then
    echo ""
    echo "================================"
    echo "  M3 is running!"
    echo "================================"
    echo ""
    echo "  Web UI:  http://localhost"
    echo "  API:     http://localhost:8000/api/v1/status"
    echo "  MinIO:   http://localhost:9001"
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
