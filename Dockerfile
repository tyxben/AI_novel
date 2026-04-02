# ============================================================
# AI 创意工坊 — 后端 API (FastAPI)
# ============================================================
FROM python:3.11-slim AS backend

WORKDIR /app

# System deps (FFmpeg for video assembly)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python deps — install extras for cloud APIs (no GPU)
COPY pyproject.toml setup.cfg* README.md ./
COPY main.py mcp_server.py config.yaml ./
COPY src/ src/

RUN pip install --no-cache-dir -e '.[web,llm,gemini,cloud-image,cloud-video,agent,mcp,ppt]'

# Workspace volume
RUN mkdir -p workspace
VOLUME /app/workspace

EXPOSE 8000

ENV API_HOST=0.0.0.0
CMD ["python", "-m", "src.api.app"]


# ============================================================
# AI 创意工坊 — 前端 (Next.js standalone)
# ============================================================
FROM node:20-alpine AS frontend-deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false

FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY --from=frontend-deps /app/node_modules ./node_modules
COPY frontend/ .
RUN mkdir -p public
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS frontend
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=frontend-build /app/.next/standalone ./
COPY --from=frontend-build /app/.next/static ./.next/static
COPY --from=frontend-build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
