# Local / self-hosted image: API + web app + in-process worker (docker-compose). In AWS the API runs on Lambda
# (Dockerfile.lambda), the web app on CloudFront and all loan data processing on Glue.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Microsoft ODBC driver for RDS SQL Server (OS packages track the pinned base image; Trivy gates CVEs in CI)
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/ms.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/ms.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pyodbc==5.2.0
COPY backend/lbp ./lbp
COPY backend/migrations ./migrations
COPY backend/alembic.ini .
COPY aws/glue /app/aws/glue
COPY aws/stepfunctions /app/aws/stepfunctions
COPY aws/lambdas /app/aws/lambdas
COPY --from=web /web/dist /app/frontend/dist
ENV LBP_REPO_ROOT=/app
RUN useradd -m -u 10001 lbp && chown -R lbp /app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fs http://localhost:8000/api/health || exit 1
# --proxy-headers: client IPs from a fronting proxy; no --reload; access log is emitted as JSON by the app
CMD ["uvicorn", "lbp.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
