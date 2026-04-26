FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        make \
        ghostscript \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY ate/ ./ate/

RUN pip install --no-cache-dir -e ".[dev]"

COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY Makefile ./

ENTRYPOINT ["ate"]
CMD ["--help"]
