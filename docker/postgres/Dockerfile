# PostGIS (spatial) + pgvector (re-ID embeddings) in one Postgres 16 image.
FROM postgis/postgis:16-3.4

# The image is Debian bullseye, which apt.postgresql.org no longer serves (404 since
# 2026-10-01): its packages moved to apt-archive.postgresql.org.
RUN sed -i 's|https\?://apt.postgresql.org|https://apt-archive.postgresql.org|' \
        /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null; \
    apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
