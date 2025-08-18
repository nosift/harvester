# build: docker buildx build --platform linux/amd64 -f Dockerfile -t wzdnzd/harvester:latest --build-arg PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple" .

FROM python:3.12.3-slim

LABEL maintainer="wzdnzd" \
      org.opencontainers.image.title="Harvester" \
      org.opencontainers.image.description="Universal Data Acquisition Framework" \
      org.opencontainers.image.source="https://github.com/wzdnzd/harvester" \
      org.opencontainers.image.documentation="https://github.com/wzdnzd/harvester/blob/main/README.md"

# GitHub credentials
ENV GITHUB_SESSIONS=""
ENV GITHUB_TOKENS=""

# Application configuration
ENV CONFIG_FILE="config.yaml" \
    LOG_LEVEL="INFO" \
    STATS_INTERVAL="15"

# pip default index url
ARG PIP_INDEX_URL="https://pypi.org/simple"

WORKDIR /harvester

# Copy all files and setup in one layer
COPY . /harvester/
RUN pip install -i ${PIP_INDEX_URL} --no-cache-dir -r requirements.txt \
    && chmod +x /harvester/entrypoint.sh \
    && groupadd -r harvester \
    && useradd -r -g harvester harvester \
    && chown -R harvester:harvester /harvester

# Switch to non-root user
USER harvester

# Set entrypoint
ENTRYPOINT ["/harvester/entrypoint.sh"]
