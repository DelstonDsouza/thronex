"""Client for the host agent. The backend never runs Docker itself."""

import httpx

from app.core.config import settings


class AgentError(Exception):
    """The agent is unreachable, refused the request, or Docker failed."""


def _call(method: str, path: str, timeout: float) -> dict:
    if not settings.agent_key:
        raise AgentError("AGENT_KEY is not configured on the backend")
    try:
        response = httpx.request(
            method,
            f"{settings.agent_url}{path}",
            headers={"X-Agent-Key": settings.agent_key},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise AgentError(f"Host agent unreachable: {exc}") from exc
    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise AgentError(f"Agent refused or failed ({response.status_code}): {detail}")
    return response.json()


def restart_container(container: str) -> str:
    return _call("POST", f"/containers/{container}/restart", timeout=75.0)["result"]


def container_status(container: str) -> dict:
    return _call("GET", f"/containers/{container}/status", timeout=20.0)