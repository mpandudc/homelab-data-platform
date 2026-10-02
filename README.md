# homelab-data-platform

Self-hosted data platform for one Proxmox LXC (`data`, 4 vCPU, 8 GB): MinIO,
ClickHouse, Redpanda + Console, Airflow, Metabase and a dbt docs site, with
scoped credentials, backups to object storage, Prometheus endpoints, and web
UIs published on `*.cahyo.tech` through Cloudflare Tunnel + Access.

It is the shared runtime for the other homelab data repos:
[dbt-clickhouse-marts](https://github.com/mpandudc/dbt-clickhouse-marts),
[airflow-data-orchestration](https://github.com/mpandudc/airflow-data-orchestration),
[postgres-cdc-redpanda](https://github.com/mpandudc/postgres-cdc-redpanda).

```
                    Cloudflare Access ─ Tunnel (outbound only, profile: edge)
                              │
  airflow.  metabase.  minio.  clickhouse.  redpanda.  dbt.   *.cahyo.tech
     │          │        │         │            │        │
┌────┴───┐ ┌────┴───┐ ┌──┴──┐ ┌────┴─────┐ ┌────┴────┐ ┌─┴──────┐
│Airflow │ │Metabase│ │MinIO│ │ClickHouse│ │Redpanda │ │dbt docs│
│web+sch │ │        │ │     │ │raw→marts │ │+Console │ │static  │
└───┬────┘ └───┬────┘ └──┬──┘ └──┬───┬───┘ └─────────┘ └────────┘
    └─platform-db─┘      │       │   └── BACKUP/RESTORE → s3://ch-backups
     (airflow, metabase) │       └── :9363 metrics ─┐
                         └── :9000/minio/v2/metrics ┴─► Prometheus on LXC 207
```

## Profiles and memory budget

| Profile | Services | mem_limit |
|---|---|---|
| core | minio, clickhouse (+ minio-init) | 384 + 1536 MB |
| stream | redpanda, redpanda-console | 768 + 128 MB |
| orchestration | airflow-webserver, airflow-scheduler, platform-db (+ airflow-init) | 1024 + 768 + 384 MB |
| bi | metabase, platform-db | 1024 MB |
| docs | dbt-docs | 384 MB |
| edge | cloudflared | 64 MB |

Long-running total 6,464 MB, below the 6.5 GiB budget that
`scripts/check_project.py` enforces, leaving the rest of the 8 GB for the OS and
ClickHouse page cache.

## Security model

- Secrets only from a generated, gitignored `.env` (`make env`); compose fails
  fast if one is missing. No literal secrets in compose (checked).
- ClickHouse users: `admin` for operations; `dbt` read/write on `raw`,
  `staging`, `intermediate`, `marts`, `ops` and read on `cdc`, cannot create
  databases; `metabase` read-only on `marts` and `ops`, cannot see `raw`.
- MinIO: ClickHouse backs up with a dedicated `clickhouse-backup` user whose
  policy covers only the `ch-backups` bucket (versioned). `bronze` expires
  objects after 90 days.
- Postgres: one database and owner per app (`airflow`, `metabase`).
- Every container: `no-new-privileges`, memory limit, healthcheck.
- Public exposure only through the tunnel, each hostname behind Cloudflare
  Access ([edge/README.md](edge/README.md)).

## Run

```bash
make env check        # generate secrets; offline policy checks
make up               # all profiles except edge
make backup           # BACKUP DATABASE marts TO S3 (MinIO)
make up-edge          # after edge/config.yml + tunnel credentials exist
make verify           # full proof on shifted ports beside the live stack
```

Moving the current `~/data-stack` on LXC 206 onto this platform:
[docs/MIGRATION.md](docs/MIGRATION.md).

See [VERIFICATION.md](VERIFICATION.md).
