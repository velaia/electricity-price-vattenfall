FROM python:3.12-slim
COPY --chown=user --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app


ADD uv.lock /app/uv.lock
ADD pyproject.toml /app/pyproject.toml
ADD main.py /app/main.py

RUN uv sync --no-dev --frozen --no-install-project

CMD ["uv", "run", "main.py"]