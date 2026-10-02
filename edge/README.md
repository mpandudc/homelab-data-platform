# Edge: web UIs on *.cahyo.tech

Outbound-only Cloudflare Tunnel from LXC 206, same pattern as the other
homelab services (see the vault runbook `domain-migration-runbook`). Nothing
listens on a public port.

| Hostname | Service | What you get |
|---|---|---|
| `airflow.cahyo.tech` | airflow-webserver:8080 | DAGs, runs, logs |
| `metabase.cahyo.tech` | metabase:3000 | Dashboards on `marts` (read-only ClickHouse user) |
| `minio.cahyo.tech` | minio:9001 | Object-store console (S3 API stays LAN/Tailscale) |
| `clickhouse.cahyo.tech` | clickhouse:8123 | `/play` SQL UI |
| `redpanda.cahyo.tech` | redpanda-console:8080 | Topics, consumer lag, Kafka Connect |
| `dbt.cahyo.tech` | dbt-docs:8080 | Lineage graph and model/column catalog |

## Access policy (do this before routing DNS)

Every hostname above is an admin surface. Create one Cloudflare Access
self-hosted application per hostname (or one with all six as additional
domains) with an **Allow** policy limited to the owner's identity, session
duration 24 h. Airflow, MinIO and Metabase keep their own logins behind
Access as a second factor. ClickHouse `/play` still requires ClickHouse
credentials.

## One-time setup (on LXC 206, cloudflared CLI with the account cert)

```bash
cloudflared tunnel login                         # once per host; writes ~/.cloudflared/cert.pem
cloudflared tunnel create lxc206-data            # prints the tunnel id, writes <id>.json
TUNNEL_ID=<id printed above>
cp ~/.cloudflared/"$TUNNEL_ID".json edge/
sed "s/<tunnel-id>/$TUNNEL_ID/g" edge/config.example.yml > edge/config.yml
for h in airflow metabase minio clickhouse redpanda dbt; do
  cloudflared tunnel route dns lxc206-data "$h.cahyo.tech"
done
make up-edge
```

`edge/config.yml` and `edge/*.json` are gitignored: the JSON is the tunnel's
secret. Before `route dns`, delete any old A record for the same name
(homeserver gotcha #4).

## Check

```bash
docker run --rm -v "$PWD/edge:/e:ro" cloudflare/cloudflared:2026.9.3 \
  tunnel --config /e/config.yml ingress validate
curl -sI https://airflow.cahyo.tech | head -1     # expect 302 to Cloudflare Access
```
