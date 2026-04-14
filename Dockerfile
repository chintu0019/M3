# Stage 1: Build the React client
FROM node:20-alpine AS client-builder

WORKDIR /app/client
COPY client/package.json client/package-lock.json* ./
RUN npm install
COPY client/ ./
RUN npm run build

# Stage 2: Build the Python server
FROM python:3.12-slim AS server-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY server/pyproject.toml .
COPY server/m3/ m3/
RUN pip install --no-cache-dir .

# Stage 3: Runtime
FROM python:3.12-slim

WORKDIR /app

COPY --from=server-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=server-builder /usr/local/bin/ /usr/local/bin/
COPY server/ .
COPY --from=client-builder /app/client/dist /app/static

EXPOSE 8000

CMD ["uvicorn", "m3.main:app", "--host", "0.0.0.0", "--port", "8000"]
