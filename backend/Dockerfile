# FootballIQ backend (FastAPI replay service). Runs on any container host; built for
# Oracle Cloud Always Free (ARM64 Ampere A1) but arch-independent (slim base is multi-arch).
# Fabric mode reads OneLake at runtime; no data is baked into the image.
FROM python:3.11-slim

# System deps: delta-rs/pyarrow wheels are self-contained, but keep ca-certificates fresh.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching). Copy only what pip needs to resolve.
COPY pyproject.toml ./
COPY footballiq ./footballiq
RUN pip install --no-cache-dir -e '.[fabric,ml]'

# Runtime cache dir (Fabric query cache). Writable, not persisted across deploys.
ENV FOOTBALLIQ_DATA_DIR=/app/data
RUN mkdir -p /app/data

# Lean memory/startup profile (override at runtime via env/compose):
#   cache 2 matches (~300 MB) instead of 4; no preload so boot doesn't block on a match load.
ENV FOOTBALLIQ_SOURCE=fabric \
    FOOTBALLIQ_CACHE_MATCHES=2 \
    FOOTBALLIQ_PRELOAD="" \
    FOOTBALLIQ_EVENTSTREAM=off

EXPOSE 8000

# Single worker: the app holds a warm in-memory LRU cache and a background warm thread,
# so multiple workers would each load matches independently. Scale with more machines, not workers.
CMD ["uvicorn", "footballiq.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
