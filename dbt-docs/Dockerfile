FROM python:3.12-slim

# Same pinned commit of mpandudc/dbt-clickhouse-marts that Airflow runs.
ARG DBT_MARTS_REF=49d9f4977d3efb4827049cd70c175401ae2eccc2

ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
ADD https://github.com/mpandudc/dbt-clickhouse-marts/archive/${DBT_MARTS_REF}.tar.gz /tmp/dbt-marts.tar.gz
RUN mkdir -p /opt/dbt-project \
    && tar -xzf /tmp/dbt-marts.tar.gz -C /opt/dbt-project --strip-components=1 \
    && rm /tmp/dbt-marts.tar.gz \
    && pip install -r /opt/dbt-project/requirements.txt \
    && useradd --create-home --uid 1000 docs
COPY serve.sh /usr/local/bin/serve.sh

USER docs
EXPOSE 8080
ENTRYPOINT ["/bin/sh", "/usr/local/bin/serve.sh"]
