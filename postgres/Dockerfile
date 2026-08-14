FROM postgres:17-alpine

LABEL org.opencontainers.image.title="HE SDK PostgreSQL storage" \
      org.opencontainers.image.description="Staging metadata and encrypted-artifact store"

COPY --chown=postgres:postgres init/ /docker-entrypoint-initdb.d/

EXPOSE 5432

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=10 \
  CMD pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" || exit 1
