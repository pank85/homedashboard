# python:3.12.11-slim-bookworm is the pinned tag (Docker Hub tag_status active).
# Runs as root: the docker socket group id differs by host, so a hardcoded GID would violate C1.
# v1 does not drop privileges. No USER. One published port: 8080.
FROM python:3.12.11-slim-bookworm

# nodejs: herdr-web-ui preflight.sh requires Node >= 18 on PATH. Bookworm's nodejs is 18.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        unzip \
        bash \
        nodejs \
    && rm -rf /var/lib/apt/lists/*

# Do not ENV PORT or HOST. The entrypoint passes those only on herdr child commands.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/usr/local/bin:/root/.local/bin:/root/.bun/bin:${PATH}"

# Bun >= 1.4. Best-effort: a failed install must not fail the image build.
ARG BUN_VERSION=1.4.3
RUN curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_VERSION}" || echo "bun install failed; continuing"; \
    if [ -e /root/.bun/bin/bun ]; then ln -sfn /root/.bun/bin/bun /usr/local/bin/bun; fi

# Herdr install is best-effort. FR5 off/external must still produce a runnable image.
RUN curl -fsSL https://herdr.dev/install.sh | bash || echo "herdr install failed; continuing"

# Plugin clones and builds devswha.herdr-web-ui. Skip cleanly when herdr is absent.
RUN if command -v herdr >/dev/null 2>&1; then \
      herdr plugin install devswha/herdr-web-ui --yes || echo "herdr plugin install failed; continuing"; \
    else \
      echo "herdr not on PATH; skipping plugin install"; \
    fi

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
