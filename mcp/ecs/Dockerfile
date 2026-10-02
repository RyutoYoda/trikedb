FROM python:3.12-slim AS base
WORKDIR /app
COPY entrypoint.py /app/entrypoint.py
RUN useradd --uid 10001 --create-home trikedb
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
ENTRYPOINT ["python", "/app/entrypoint.py"]

# For pre-release verification only: place exactly one wheel in dist/.
FROM base AS wheel
COPY dist/ /tmp/wheels/
RUN python -c "import glob,subprocess; p=glob.glob('/tmp/wheels/trikedb-*.whl'); assert len(p)==1; subprocess.check_call(['pip','install','--no-cache-dir',p[0]+'[serve,remote,oauth]'])" && rm -rf /tmp/wheels
USER 10001

# Normal public build installs the released library from PyPI.
FROM base AS release
ARG TRIKEDB_VERSION=0.36.0
RUN pip install --no-cache-dir "trikedb[serve,remote,oauth]==${TRIKEDB_VERSION}"
USER 10001
