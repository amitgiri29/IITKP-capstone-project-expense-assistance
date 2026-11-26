# syntax=docker/dockerfile:1
# One image for both services; compose.yaml picks the command.
# DEP01: pin the tested digest once built, e.g. --build-arg PYTHON_IMAGE=python:3.14.10-slim@sha256:<digest>
ARG PYTHON_IMAGE=python:3.14.10-slim@sha256:af8a5aa14780025dbfbcfbc81bd8a91ebd87711dd5b0f48ed71090949dd7cb1d
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.lock.txt ./
RUN python -m pip install -r requirements.lock.txt

# Application code and normative data only. Golden answer keys (tests/), docs,
# uploads, runtime state and .env never enter the image (DEP01).
COPY IMPLEMENTATION_CONTRACT.json ./
COPY config ./config
COPY assets ./assets
COPY .streamlit ./.streamlit
COPY policy_sources ./policy_sources
COPY schemas ./schemas
COPY fixtures/search ./fixtures/search
COPY domain ./domain
COPY core ./core
COPY adapters ./adapters
COPY retrieval ./retrieval
COPY workflows ./workflows
COPY api ./api
COPY ui ./ui

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/runtime && chown app:app /app/runtime
USER app

EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
