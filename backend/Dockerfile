# The API, and the ingestion CLI that shares its code.
#
# The image mirrors the repository layout on purpose: the app resolves its
# project root by walking up from `app/db/base.py` (PROJECT_ROOT = parents[3]),
# and the Data Dragon cache hangs off that. Putting the code at an arbitrary
# path would silently move `data/static` somewhere that is not the volume, and
# the first symptom would be champion icons vanishing after a redeploy. So:
# code at /srv/riftline/backend, data volume at /srv/riftline/data, identical to
# a developer's checkout.
FROM python:3.12-slim

# Python 3.12 is a hard requirement (pyproject: requires-python >= 3.12) and the
# host runs 3.10, which is the reason this is containerised at all.

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/riftline/backend

# Requirements first: this layer is the slow one and only changes when a pin
# does, so day-to-day deploys reuse it.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements.txt

# The dev extras (pytest, respx, ruff) are installed in the same image rather
# than a second one, because CI runs the suite inside the artefact it deploys.
# That is the point: the tests exercise the image, not an approximation of it.
RUN pip install -r requirements-dev.txt

COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

# Created so a first run with no volume mounted still works; the compose file
# mounts over it.
RUN mkdir -p /srv/riftline/data

EXPOSE 8000

# One worker. The workload is IO-bound against Riot and SQLite, and SQLite with
# several writing processes is how you earn "database is locked": the ingestion
# CLI already competes for the same file.
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--log-level", "warning"]
