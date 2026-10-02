# Verification evidence

Verified on 2026-10-02 (Asia/Jakarta) with `make check` and `make verify` on
Proxmox LXC 206 `data` (4 vCPU, 8 GB RAM, Docker 29.1.3), as compose project
`hdp-verify` with every port shifted by +20000 and fresh random secrets, next
to the live `~/data-stack`, which kept running untouched.

`scripts/verify_runtime.py`: 26/26 checks passed.

- All 9 long-running services healthy (profiles core, stream, orchestration,
  bi, docs); `minio-init` and `airflow-init` exited 0. Cold start 85 s with
  images cached.
- MinIO: buckets `bronze`, `silver`, `ch-backups`; 90-day expiry on `bronze`;
  scoped `clickhouse-backup` user.
- ClickHouse scoping: `metabase` reads `marts`, cannot write, cannot read
  `raw`; `dbt` creates tables in `staging`, cannot create databases.
- `BACKUP DATABASE marts` to MinIO, then `RESTORE ... AS marts_restore`:
  10,000 rows, identical sum.
- Redpanda produce/consume round trip.
- Web UIs that `edge/config.yml` publishes all answered 200: Airflow,
  Metabase, MinIO console, ClickHouse `/play`, Redpanda Console, dbt docs.
- Prometheus endpoints: ClickHouse `:9363/metrics`, Redpanda
  `/public_metrics`, MinIO `/minio/v2/metrics/cluster`.
- Airflow `platform_smoke` DAG reached all four services, none skipped.
- `cloudflared tunnel ingress rule https://dbt.cahyo.tech` resolved to `dbt-docs:8080`.

Problems found and fixed during verification:

| Symptom | Cause | Fix |
|---|---|---|
| `minio` pull 401 | MinIO no longer publishes `RELEASE.*` tags | pin by digest |
| dbt docs: "Failed to create analytics database" | dbt-clickhouse creates the profile schema on connect | bootstrap creates `analytics`, granted to `dbt` |
| ClickHouse init `/bin/bash^M` | CRLF from a Windows edit | `.gitattributes eol=lf`, files normalised |
| `up --wait` fails | finished one-shot `minio-init` counted as failure | poll health instead |
| Airflow webserver 766/768 MiB, Metabase 1023/1024 MiB | limits too tight | webserver 1 worker and 1 GiB (scheduler 1 GiB → 768 MiB, used ~430), Metabase `-Xmx512m` |
| Metabase crash loop | `-XX:MaxMetaspaceSize=192m` | cap removed |

The recorded run used webserver 768 MiB / scheduler 1 GiB; the swap to
1 GiB / 768 MiB was then checked separately: orchestration profile healthy,
`platform_smoke` passed, webserver 908 MiB of 1 GiB, scheduler 426 MiB of 768 MiB.

Raw numbers: [results/verification.json](results/verification.json).

Not verified here: the live tunnel and Cloudflare Access (needs the account),
and the migration of `~/data-stack` ([docs/MIGRATION.md](docs/MIGRATION.md)).
