FROM python:3.12-slim

# The herdr CLI version must equal the version of the herdr server on the host.
ARG HERDR_VERSION=0.9.5

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

RUN mkdir -p /usr/share/doc/herdr \
    && python -c "import platform, urllib.request as r; r.urlretrieve( \
      'https://github.com/herdrdev/herdr/releases/download/v${HERDR_VERSION}/herdr-linux-' \
      + platform.machine(), '/usr/local/bin/herdr'); r.urlretrieve( \
      'https://raw.githubusercontent.com/herdrdev/herdr/v${HERDR_VERSION}/LICENSE', \
      '/usr/share/doc/herdr/LICENSE')" \
    && chmod 755 /usr/local/bin/herdr

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    HERDR_MCP_HOST=0.0.0.0 \
    HERDR_MCP_PORT=8765 \
    HERDR_SOCKET_PATH=/herdr/herdr.sock
EXPOSE 8765
CMD ["herdr-mcp"]
