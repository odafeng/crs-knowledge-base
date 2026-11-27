# Paper Watch worker (E3 #76): the existing Python pipeline as a Cloud Run job that writes content and tracking state
# to PostgreSQL (ADR-0021). Build from the repository root: docker build -f worker/Dockerfile .
# Runtime environment: GUTHUB_CONTENT_DATABASE_URL, ANTHROPIC_API_KEY, GH_TOKEN, GITHUB_REPOSITORY; optional
# NCBI_API_KEY, LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID.
FROM python:3.12-slim

# gh opens the review issues for held papers; pinned and checked against the release checksums.
ARG GH_VERSION=2.103.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && cd /tmp \
 && curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
 && curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
 && grep "gh_${GH_VERSION}_linux_amd64.tar.gz" "gh_${GH_VERSION}_checksums.txt" | sha256sum -c - \
 && tar -xzf "gh_${GH_VERSION}_linux_amd64.tar.gz" \
 && mv "gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh \
 && rm -rf /tmp/gh_* \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]==3.3.9"
COPY scripts ./scripts
COPY newsroom ./newsroom
COPY contracts/taxonomy.json ./contracts/taxonomy.json
COPY import_content.py content_writer.py ./
COPY worker ./worker
RUN mkdir -p data docs && chown -R 65532:65532 data docs

ENV PYTHONUNBUFFERED=1
USER 65532:65532
ENTRYPOINT ["python", "/app/worker/run.py"]
