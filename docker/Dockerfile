# Imagen de Airflow con las dependencias del motor de reposición.
FROM apache/airflow:3.3.2-python3.11

USER root
# libgomp1: OpenMP para LightGBM. git: versionado con plumbing y DVC.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    # el repo se monta desde el host con otro propietario: git debe confiar en él
    && git config --system --add safe.directory '*'

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
