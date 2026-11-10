# Session 04 / Exercise 03 — StoreX Environment Security and Networking

This uses the authorized minimal Spring Boot JDBC fixture from
[Exercise 01](https://github.com/ng-trng-phcc/md05_ss04_bai_01), with the
digest-pinned build approach from Exercise 02. The original StoreX v3 backend
source/image was not supplied. This fixture demonstrates configuration,
networking, and real SQL connectivity, not StoreX business functionality.

## Security objective and configuration

Hardcoded/shared database credentials in Compose can leak through source
control, screenshots, logs, and copied deployment files. The Compose source
instead uses required `${DB_HOST:?…}`, `${DB_NAME:?…}`, `${DB_USER:?…}`, and
`${DB_PASS:?…}` interpolation. Missing/empty required values fail validation.

- `.env`: actual locally generated non-production password; local only, mode
  0600, ignored by Git, excluded from the Docker build context.
- `.env.example`: example configuration with a placeholder password, safe to
  commit. It is not a working credential file.
- Compose maps these values explicitly to `SPRING_DATASOURCE_URL`,
  `SPRING_DATASOURCE_USERNAME`, `SPRING_DATASOURCE_PASSWORD` and matching
  PostgreSQL initialization variables. Spring Boot does not automatically
  interpret arbitrary `DB_*` variables as datasource settings.
- Effective JDBC URL for the local example:
  `jdbc:postgresql://postgres:5432/storex`.
- Do not print `.env`, unredacted `docker compose config`, `config --environment`,
  or full container inspect output. These can reveal runtime credentials.
- Compose's shell environment can override `.env`; unset unintended `DB_*`
  exports before using this project.

Environment variables and an ignored file are **not Docker secrets or an
external secret manager**. Docker administrators can inspect container
environment values; the local file and PostgreSQL volume require protection.
This lab does not claim production-grade secret management. The official
PostgreSQL image makes `POSTGRES_USER` the initialization superuser; least-
privilege application roles are outside this minimal assignment fixture.

## Network and runtime architecture

- Project `rikkei-ss04-storex03`: backend `storex-backend:v3`, `postgres:13`.
- Backend publishes the required `8080:8080`.
- PostgreSQL publishes **no host port**. Host PostgreSQL remains unchanged.
- Both services explicitly join Compose-managed network key `storex-net`,
  whose actual Docker name is **`storex-net`**, driver **bridge**. Compose labels
  identify ownership. Because the explicit Docker name is global on this daemon,
  check it for conflicts rather than replacing an existing unrelated network.
- PostgreSQL healthcheck uses TCP `pg_isready` with container environment
  variables; `$$` defers their expansion to the healthcheck's container shell.
- Backend waits for `service_healthy` and runs a real startup SQL query.
- Named volume `rikkei-ss04-storex03_postgres-data` preserves the database,
  separate from previous exercises. No existing volumes are reused/deleted.

Docker service-name DNS resolves `postgres` for peers on the same user-defined
network. A separate network normally cannot use that service DNS or directly
access its unpublished database port. DNS failure alone is not proof of traffic
isolation, so the acceptance check tests both name lookup and TCP to the actual
database container address. The temporary test container is never attached to
`storex-net` and never uses host networking.

This is not a boundary against the Docker host or privileged Docker users.
The host may directly access bridge container addresses; Docker administrators
can attach other containers or alter networking. Same-network peers can access
the database port. Published backend port 8080 remains reachable according to
host firewall rules. Cross-network behavior depends on Docker routing/firewall
configuration; tests record the observed outcome, not a universal guarantee.

## Reproduce

Requires Docker/Compose, Python 3, registry/Maven Central access, and free host
port 8080. Exercise 02 was stopped using project-scoped `compose stop` with
authorization; its containers/network/volume remain intact. Exercise 01 and
unrelated services were not stopped by this task.

```bash
docker network ls --filter name='^storex-net$'
ss -ltnp '( sport = :8080 )'
python3 scripts/setup-env.py
docker build -t storex-backend:v3 .
docker image inspect storex-backend:v3 --format '{{.Id}}'
docker compose config -q
python3 scripts/verify-security.py static
docker compose up -d
docker compose ps
curl -i http://localhost:8080/db-check
# Fetch the official test image if ubuntu:24.04 is not already available locally.
docker image inspect ubuntu:24.04 --format '{{.Id}}' || docker pull ubuntu:24.04
python3 scripts/verify-security.py runtime --output /tmp/storex03-security-results.json
```

The setup script refuses to overwrite an existing `.env`. Do not regenerate a
password for an existing initialized volume without a planned database password
change: PostgreSQL initialization environment variables only apply to empty
data directories. Do not solve mismatches by deleting data.

The multi-stage Dockerfile uses Java 21 / Maven 3.9.11 with digest-pinned build
and runtime images, Spring Boot 3.5.16 dependency management, and a fixed JAR
timestamp. It runs unprivileged and embeds no datasource credentials. The
official `postgres:13` service tag remains mutable; the tested digest is recorded
with the actual results. No local Maven installation is required.

The verification script prints only redacted effective configuration and safe
results. Runtime mode checks SQL, network membership, absent database host
bindings, internal DNS/TCP, and an isolated disposable container using the local
official `ubuntu:24.04` test image. It removes only that test container afterward.

`/db-check` executes `SELECT 1`, `current_database()`, and server address/port on
every request through JdbcTemplate, returning HTTP 200 only on success and HTTP
503 on query failure. `docker compose ps` alone does not prove connectivity.

## Actual results and evidence

Verified on **2026-11-11 (UTC+07:00)** using Docker 29.5.3 and Compose 5.1.4.

| Check | Observed result |
|---|---|
| Build | Maven `BUILD SUCCESS`; `storex-backend:v3` runs on Temurin 21.0.13 |
| Static Compose | `docker compose config -q` passed; redacted effective configuration checked |
| Required inputs | Each of `DB_HOST`, `DB_NAME`, `DB_USER`, and `DB_PASS` was rejected when missing and when empty |
| PostgreSQL | `postgres:13` healthy; backend started with zero restarts and no observed datasource connection/authentication errors |
| Real SQL | HTTP 200, `queryExecuted=true`, `database=storex`, `queryResult=1`; backend logs showed HikariCP adding a PostgreSQL connection |
| Network | Docker network `storex-net`, driver `bridge`, labeled for `rikkei-ss04-storex03`; members were exactly backend and PostgreSQL |
| PostgreSQL exposure | Docker reported `{"5432/tcp":null}`: internal port, no host binding |
| Backend DNS / TCP | `postgres` resolved to `172.26.0.2`; TCP to `postgres:5432` succeeded; SQL reported that same PostgreSQL address |
| Separate bridge: DNS | Disposable container on `bridge` only: `getent hosts postgres` exited `2` (no result) |
| Separate bridge: direct TCP | TCP to the observed database address `172.26.0.2:5432` timed out after 4 seconds (exit `124`); test container removed |
| Local credential hygiene | `.env` mode `0600`; ignored and untracked. `.env.example` has a placeholder. Checks found no generated password in publishable source, service logs, backend image configuration, or screenshot text |

These are results for this run. Container IPs are dynamic and are not stored in
the deployment configuration. The isolation result applies to the tested
container and Docker network policy, not to the host or Docker administrators.

Resolved image IDs used for this run:

```text
storex-backend:v3  sha256:1140363aa7fb2012d94a86f0b41200c1786f5b7f44a063298bcae1e8b7b570fe
postgres:13        sha256:4689940c683801b4ab839ab3b0a0a3555a5fe425371422310944e89eca7d8068
```

### Evidence

Unmodified 2560×1440 Foot captures from Hyprland, taken with `grim`, are
attached to [Release ss04-bai-03](https://github.com/ng-trng-phcc/md05_ss04_bai_03/releases/tag/ss04-bai-03).
PNG integrity and OCR checks passed. The capture script checked each terminal
output block for the generated password before displaying it.

- [evidence_03.png](https://github.com/ng-trng-phcc/md05_ss04_bai_03/releases/download/ss04-bai-03/evidence_03.png):
  live service status, SQL result, network members, and unpublished database port.
- [evidence_03_security.png](https://github.com/ng-trng-phcc/md05_ss04_bai_03/releases/download/ss04-bai-03/evidence_03_security.png):
  local file permissions and Git ignore checks, live internal DNS/TCP, and the
  recorded isolated-container results.

```text
a6d882be6806186e983af8fbb56e3a7be6499e71d7f2e9538b400b495b2413ec  evidence_03.png
804dbeaa34df113e904ddc8543f59268e576ff826a3251556d1cfbfceca26c0a  evidence_03_security.png
```

The authorized Exercise 02 stop preserved its three containers, network, and
named database volume. A post-stop baseline audit found all 34 existing
containers, 11 networks, 42 volumes, and 29 images preserved. Prior assignment
files, host PostgreSQL, and global Git identity were unchanged. Exercise 03
added its two running containers, `storex-net`, named PostgreSQL volume,
backend v3 image, and build cache. The disposable isolation container was removed.

Keep the verified stack running. A later intentional `docker compose stop`
preserves containers/data; do not delete volumes or run global Docker cleanup.
