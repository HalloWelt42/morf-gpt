# Backend samt gebauter Oberfläche in einem Abbild - für den Betrieb der Bibliothek
# an einem anderen Ort (ohne Werkstatt-Dienste). Zwei Stufen: Oberfläche bauen, dann
# Python-Laufzeit mit ffmpeg (nur für optionale Audio-Wiedergabe-Umwandlung).
FROM node:22-alpine AS oberflaeche
WORKDIR /bau
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
COPY version.json ../version.json
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock* ./backend/
RUN cd backend && uv pip install --system -r pyproject.toml
COPY backend/ ./backend/
COPY version.json ./version.json
COPY --from=oberflaeche /bau/dist ./frontend/dist
WORKDIR /app/backend
EXPOSE 8460
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host ${MORF_BACKEND_HOST:-0.0.0.0} --port ${MORF_BACKEND_PORT:-8460}"]
