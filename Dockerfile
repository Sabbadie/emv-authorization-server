# ────────────────────────────────────────────────────────────────
# EMV Authorization Server — Dockerfile multi-stage
# Étape 1 : installation des dépendances (builder)
# Étape 2 : image d'exécution allégée (runtime)
# ────────────────────────────────────────────────────────────────

# ── Étape 1 : builder ────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Étape 2 : runtime ────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="EMV Auth Server" \
      version="1.4.0" \
      description="Serveur d'autorisation EMV 4.3 / ISO 8583"

WORKDIR /app

COPY --from=builder /install /usr/local

COPY . .

RUN mkdir -p /app/data

EXPOSE 5000 8583

ENV HOST=0.0.0.0 \
    PORT=5000 \
    DEBUG=false \
    TCP_ENABLED=true \
    TCP_HOST=0.0.0.0 \
    TCP_PORT=8583 \
    SNAPSHOT_ENABLED=true \
    SNAPSHOT_INTERVAL_SECS=120

CMD ["python", "main.py"]
