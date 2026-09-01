"""An MCP subprocess gets an ALLOWLISTED environment, not the whole of os.environ.

Found by adversarial review, 2026-08-27, while checking whether RFC 0018's
decision 6 buys what it claims. `_ensure_session` spawned every subprocess with
`{**os.environ, **overrides}`. Under Lambda `os.environ` carries
`ADMIN_API_KEY` and the task role's `AWS_SESSION_TOKEN` — a role holding
`PutItem`, `DeleteItem`, `TransactWriteItems` and `Scan`.

So the CUSTOMER MCP server has been holding a full-write admin credential all
along. Decision 6's process boundary is tool-SURFACE isolation and confers no
privilege isolation whatsoever: "a process that never loaded the tool cannot
leak it" is true of the model's tool namespace and false of the process it runs
in. That gap matters more once a second server exists whose entire premise is
that it is read-only.

An allowlist makes the boundary mean what it looks like it means.
"""

import os
from unittest.mock import patch

from merlins_collection.services.mcp_client import McpToolExecutor


def _spawn_env(**environ) -> dict:
    """The env a spawn would actually hand the child, without spawning one."""
    executor = McpToolExecutor(["true"], env={"DYNAMODB_TABLE_NAME": "t"})
    with patch.dict(os.environ, environ, clear=True):
        return executor._child_env()


def test_a_secret_in_the_parent_environment_does_not_reach_the_subprocess():
    env = _spawn_env(
        ADMIN_API_KEY="super-secret",
        POKEMONPRICETRACKER_API_KEY="also-secret",
        AUTH_SECRET="nextauth-secret",
        AWS_COGNITO_CLIENT_SECRET="cognito-secret",
    )
    for leaked in (
        "ADMIN_API_KEY",
        "POKEMONPRICETRACKER_API_KEY",
        "AUTH_SECRET",
        "AWS_COGNITO_CLIENT_SECRET",
    ):
        assert leaked not in env, f"{leaked} was handed to an MCP subprocess"


def test_the_aws_credentials_the_server_actually_needs_still_reach_it():
    """The allowlist must not break the thing it is protecting.

    Both servers read DynamoDB with the ambient credential chain, so the
    role's own variables have to survive — an allowlist that starves the
    subprocess is just an outage with better intentions.
    """
    env = _spawn_env(
        AWS_ACCESS_KEY_ID="AKIA", AWS_SECRET_ACCESS_KEY="s",
        AWS_SESSION_TOKEN="tok", AWS_REGION="us-east-1",
        AWS_CONTAINER_CREDENTIALS_RELATIVE_URI="/v2/creds",
    )
    assert env["AWS_ACCESS_KEY_ID"] == "AKIA"
    assert env["AWS_SECRET_ACCESS_KEY"] == "s"
    assert env["AWS_SESSION_TOKEN"] == "tok"
    assert env["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"] == "/v2/creds"


def test_explicit_overrides_always_win_and_always_arrive():
    """Settings-derived config is passed explicitly because pydantic-settings
    reads .env without exporting to os.environ — that must keep working."""
    env = _spawn_env(DYNAMODB_TABLE_NAME="from-the-parent")
    assert env["DYNAMODB_TABLE_NAME"] == "t"


def test_path_survives_or_nothing_can_be_spawned_at_all():
    env = _spawn_env(PATH="/usr/bin:/bin", HOME="/home/app")
    assert env["PATH"] == "/usr/bin:/bin"
