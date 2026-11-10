"""Secret-safe static/runtime acceptance checks for this assignment only."""

import argparse
import json
import os
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "rikkei-ss04-storex03"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mode", choices=("static", "runtime", "hygiene"))
parser.add_argument("--output", type=Path)
args = parser.parse_args()


def require(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)


def command(*argv, check=True, **kwargs):
    result = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    require(not check or result.returncode == 0, "command failed: " + argv[0])
    return result


env_path = ROOT / ".env"
require(env_path.is_file(), "private .env missing; run setup-env.py")
values = dict(line.split("=", 1) for line in env_path.read_text().splitlines()
              if line.strip() and not line.startswith("#"))
password = values["DB_PASS"]
require(len(password) >= 32, "generated local password must be at least 32 characters")
require(stat.S_IMODE(env_path.stat().st_mode) == 0o600, ".env permissions must be 0600")
require(values["DB_HOST"] == "postgres", "DB_HOST must use the Compose service name")


def hygiene():
    forbidden = password.encode()
    count = 0
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or ".git" in relative.parts or path == env_path or path.suffix == ".png":
            continue
        require(forbidden not in path.read_bytes(), "password found in a project file (content suppressed)")
        count += 1
    if (ROOT / ".git").is_dir():
        require(not command("git", "ls-files", ".env").stdout.strip(), ".env is tracked")
        require(command("git", "check-ignore", "-q", ".env", check=False).returncode == 0, ".env not ignored")
        for revision in command("git", "rev-list", "--all", check=False).stdout.splitlines():
            for path in command("git", "ls-tree", "-r", "--name-only", revision).stdout.splitlines():
                require(path != ".env", ".env found in history")
                blob = subprocess.check_output(["git", "show", revision + ":" + path], cwd=ROOT)
                require(forbidden not in blob, "password found in Git history (content suppressed)")
        tracked = command("git", "ls-files").stdout.splitlines()
        require(".env.example" in tracked, ".env.example must be included in submission")
    else:
        require(".env" in (ROOT / ".gitignore").read_text().splitlines(), "missing .env ignore rule")
    print(f"PASS: private .env mode 0600; password absent from {count} publishable text/source files; Git checks applied when initialized")
    return {"env_exists": True, "env_mode": "0600", "password_absent_from_project_files": True,
            "git_history_checked": (ROOT / ".git").is_dir()}


def configuration():
    require(command("docker", "compose", "config", "-q", check=False).returncode == 0, "Compose validation failed")
    config = json.loads(command("docker", "compose", "config", "--format", "json").stdout)
    b, p = config["services"]["backend"], config["services"]["postgres"]
    require(config["name"] == PROJECT and set(config["services"]) == {"backend", "postgres"}, "wrong project/services")
    require(b["image"] == "storex-backend:v3" and p["image"] == "postgres:13", "wrong images")
    require(b["environment"]["SPRING_DATASOURCE_URL"] == f"jdbc:postgresql://postgres:5432/{values['DB_NAME']}", "wrong JDBC URL")
    require(b["environment"]["SPRING_DATASOURCE_USERNAME"] == values["DB_USER"], "username mismatch")
    require(b["environment"]["SPRING_DATASOURCE_PASSWORD"] == password, "backend password mismatch")
    require(p["environment"] == {"POSTGRES_DB": values["DB_NAME"], "POSTGRES_USER": values["DB_USER"], "POSTGRES_PASSWORD": password}, "database environment mismatch")
    require(not p.get("ports"), "PostgreSQL must not publish host ports")
    require(b["ports"][0]["target"] == 8080 and b["ports"][0]["published"] == "8080", "backend port mismatch")
    require(set(b["networks"]) == set(p["networks"]) == {"storex-net"}, "wrong explicit network memberships")
    require(config["networks"]["storex-net"]["name"] == "storex-net" and config["networks"]["storex-net"]["driver"] == "bridge", "wrong network")
    require(b["depends_on"]["postgres"]["condition"] == "service_healthy", "missing health gate")
    require("pg_isready" in p["healthcheck"]["test"][-1], "missing PostgreSQL healthcheck")
    require(p["volumes"][0]["target"] == "/var/lib/postgresql/data", "wrong volume mount")
    require(config["volumes"]["postgres-data"]["name"] == PROJECT + "_postgres-data", "wrong volume name")
    source = (ROOT / "docker-compose.yml").read_text()
    require(all("${" + key + ":?" in source for key in values), "missing required-variable interpolation")
    # Test missing and empty values with no .env fallback and no actual secrets.
    for key in values:
        test_env = {k: v for k, v in os.environ.items() if k not in values}
        test_env.update({"DB_HOST": "postgres", "DB_NAME": "example", "DB_USER": "example", "DB_PASS": "PLACEHOLDER_ONLY"})
        for empty in (False, True):
            if empty:
                test_env[key] = ""
            else:
                test_env.pop(key, None)
            result = command("docker", "compose", "--env-file", "/dev/null", "config", "-q", env=test_env, check=False)
            require(result.returncode != 0 and key + " is required" in result.stderr, "required-variable rejection failed")
    for service in (b, p):
        for key in service["environment"]:
            if "PASSWORD" in key:
                service["environment"][key] = "<REDACTED>"
    print("REDACTED effective Compose configuration:")
    print(json.dumps(config, indent=2))
    print("PASS: Compose/interpolation/network/volume assertions; all four missing AND empty DB variables rejected")
    return {"compose_valid": True, "missing_and_empty_variables_rejected": list(values)}


def inspect_container(name):
    return json.loads(command("docker", "inspect", name).stdout)[0]


def runtime():
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen("http://localhost:8080/db-check", timeout=12) as response:
                body = json.load(response)
                require(response.status == 200 and body["queryResult"] == 1 and body["database"] == values["DB_NAME"], "real SQL verification failed")
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            require(time.monotonic() < deadline, "backend SQL startup timeout")
            time.sleep(1)
    backend = inspect_container(PROJECT + "-backend-1")
    postgres = inspect_container(PROJECT + "-postgres-1")
    require(backend["State"]["Running"] and backend["RestartCount"] == 0, "backend not stable")
    require(postgres["State"]["Health"]["Status"] == "healthy", "PostgreSQL not healthy")
    require(not postgres["HostConfig"]["PortBindings"], "database host binding present")
    network = json.loads(command("docker", "network", "inspect", "storex-net").stdout)[0]
    require(network["Driver"] == "bridge" and network["Labels"]["com.docker.compose.project"] == PROJECT, "network ownership/driver mismatch")
    require(set(network["Containers"]) == {backend["Id"], postgres["Id"]}, "unexpected network members")
    database_ip = postgres["NetworkSettings"]["Networks"]["storex-net"]["IPAddress"]
    require(body["serverAddress"].split("/")[0] == database_ip, "SQL response not from this database")
    dns = command("docker", "compose", "exec", "-T", "backend", "getent", "hosts", "postgres").stdout.strip()
    require(database_ip in dns, "backend DNS mismatch")
    command("docker", "compose", "exec", "-T", "backend", "bash", "-c", "timeout 4 bash -c '</dev/tcp/postgres/5432'")
    logs = command("docker", "compose", "logs", "--no-color", "backend").stdout
    require(password not in logs and "DB_CHECK SUCCESS" in logs and "ERROR" not in logs, "backend logs failed SQL/secret checks")
    require(password not in command("docker", "compose", "logs", "--no-color", "postgres").stdout, "password appeared in PostgreSQL logs")
    # Deliberately separate default bridge; never attach this container to storex-net.
    test_name = "storex03-isolation-" + uuid.uuid4().hex[:12]
    script = """set +e
getent hosts postgres >/dev/null 2>&1
dns_rc=$?
timeout 4 bash -c 'exec 3<>/dev/tcp/$1/5432' _ "$1" >/dev/null 2>&1
tcp_rc=$?
printf 'isolated_dns_exit=%s\nisolated_direct_tcp_exit=%s\n' "$dns_rc" "$tcp_rc"
test "$dns_rc" -ne 0 && test "$tcp_rc" -ne 0
"""
    try:
        command("docker", "create", "--name", test_name, "--network", "bridge", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--read-only", "--label", "assignment=rikkei-ss04-storex03-isolation",
                "--entrypoint", "bash", "ubuntu:24.04", "-c", script, "_", database_ip)
        isolated = inspect_container(test_name)
        require(set(isolated["NetworkSettings"]["Networks"]) == {"bridge"}, "test container network incorrect")
        output = command("docker", "start", "-a", test_name).stdout.strip()
        exit_code = inspect_container(test_name)["State"]["ExitCode"]
        codes = dict(line.split("=", 1) for line in output.splitlines())
        print("ISOLATED TEST:", output.replace("\n", "; "))
        require(exit_code == 0 and int(codes["isolated_dns_exit"]) != 0 and int(codes["isolated_direct_tcp_exit"]) != 0, "isolated container unexpectedly reached database")
    finally:
        # Remove only this unique disposable test container, never any project data.
        command("docker", "rm", "-f", test_name, check=False)
    remaining = command("docker", "ps", "-aq", "--filter", "name=^/" + test_name + "$").stdout.strip()
    require(not remaining, "temporary container cleanup failed")
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "http_status": 200, "sql": body,
              "network": {"name": network["Name"], "driver": network["Driver"], "project": PROJECT,
                          "members": sorted(c["Name"] for c in network["Containers"].values())},
              "postgres_healthy": True, "postgres_published_ports": False, "backend_restarts": 0,
              "internal_dns": dns, "internal_tcp_passed": True,
              "isolated_test": {"container": test_name, "network": "bridge", "database_address": database_ip,
                                "dns_exit": int(codes["isolated_dns_exit"]), "direct_tcp_exit": int(codes["isolated_direct_tcp_exit"]),
                                "removed": True}, "password_absent_from_service_logs": True}
    print("LIVE SQL:", json.dumps(body))
    print("NETWORK:", json.dumps(result["network"]))
    print("PASS: healthy database; real SQL; internal DNS/TCP; isolated DNS AND direct TCP denied; no DB host ports; test container removed")
    return result


checks = {"hygiene": hygiene()}
if args.mode in ("static", "runtime"):
    checks["static"] = configuration()
if args.mode == "runtime":
    checks["runtime"] = runtime()
if args.output:
    require(args.output.parent.is_dir(), "output parent does not exist")
    serialized = json.dumps(checks, indent=2)
    require(password not in serialized, "refusing to write secret in results")
    args.output.write_text(serialized + "\n")
    print("Secret-free results saved:", args.output)
