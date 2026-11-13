"""THRONEX host agent: the only component allowed to talk to Docker.

Exposes exactly two operations on an allowlist of containers. It never runs shell
commands, never accepts commands from callers, and listens on 127.0.0.1 only.
"""

import hmac
import os
import re
import subprocess
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException


def _load_env() -> None:
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_env()

AGENT_KEY = os.getenv("AGENT_KEY", "")
if len(AGENT_KEY) < 16:
    raise RuntimeError("AGENT_KEY must be set in .env (at least 16 characters)")

ALLOWED = {
    name.strip()
    for name in os.getenv(
        "ALLOWED_CONTAINERS", "demo-api-gateway,demo-order-service,demo-payment-service"
    ).split(",")
    if name.strip()
}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

app = FastAPI(title="THRONEX Host Agent", version="0.1.0")


def require_key(x_agent_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_agent_key, AGENT_KEY):
        raise HTTPException(401, "Invalid agent key")


def validated(name: str) -> str:
    if not NAME_PATTERN.match(name) or name not in ALLOWED:
        raise HTTPException(403, "Container is not on the allowlist")
    return name


def run_docker(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    # A fixed argument list, no shell. Only this function runs docker.
    try:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=timeout, shell=False
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise HTTPException(502, f"Docker command failed: {exc}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/containers/{name}/restart", dependencies=[Depends(require_key)])
def restart(name: str) -> dict[str, str]:
    name = validated(name)
    result = run_docker(["restart", "-t", "10", name], timeout=60)
    if result.returncode != 0:
        raise HTTPException(502, result.stderr.strip() or "docker restart failed")
    return {"container": name, "result": "restarted"}


@app.get("/containers/{name}/status", dependencies=[Depends(require_key)])
def container_status(name: str) -> dict:
    name = validated(name)
    fmt = "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
    result = run_docker(["inspect", "--format", fmt, name], timeout=15)
    if result.returncode != 0:
        raise HTTPException(404, "Container not found")
    state, _, health = result.stdout.strip().partition("|")
    return {"container": name, "running": state == "running", "state": state, "health": health}