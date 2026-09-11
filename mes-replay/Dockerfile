FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install '.[test]'

COPY tests ./tests

EXPOSE 8787

ENTRYPOINT ["mes-replay"]
CMD ["serve", "--manifest", "/data/runtime/manifest.json", "--host", "0.0.0.0", "--port", "8787"]
