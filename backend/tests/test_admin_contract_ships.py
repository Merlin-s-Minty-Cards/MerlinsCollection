"""The admin tool contract must SHIP, not just resolve in a dev checkout.

RFC-0018 roadmap fact 7 warned that "a tool server that is not in the image is
a chat that 503s in production and passes every test locally". This is that
failure, one level down: the server ships fine, but the **contract file it is
built from** did not.

`services/bedrock._admin_tool_schemas()` reads
`shared/admin-tool-contract.json` at request time, resolving it by walking up
from `bedrock.py.__file__` to the repository root. Two things make that work
here and nowhere else:

* `backend/Dockerfile` **never `COPY`s `shared/`** — it copies
  `backend/pyproject.toml`, `backend/src`, `backend/scripts` and the built
  `mcp-server/dist`, and nothing else from the repo root.
* the image installs the package NON-editable (`pip install ./backend`), so
  `__file__` is under `site-packages/` and the walk lands in
  `/usr/local/lib/`, not in a checkout at all.

So the first `POST /admin/chat/` in production raises `FileNotFoundError`
before Bedrock is ever called, while every local test passes — the dev clone is
an editable install with the repo root exactly where the walk expects it.

The fix is not a `COPY` line: a package that reads a file outside itself is
fragile in every packaging mode, and item 4's decision to write the admin
server in **Python** removed the only reason this file lived in `shared/` at
all. `shared/` exists for constants crossing the Python/TypeScript boundary
(`tool-contract.json` is read by `mcp-server/`); **nothing outside the backend
has ever read the admin contract.** It belongs in the package, beside the two
readers it has.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from merlins_collection.services.bedrock import ADMIN_TOOL_CONTRACT, _admin_tool_schemas

PACKAGE_ROOT = Path(files("merlins_collection"))


def test_the_contract_lives_inside_the_installed_package():
    """A wheel ships what is under the package root, and nothing else.

    This is the property that makes the file survive `pip install`, an editable
    install, a container image and a Lambda layer identically — as opposed to
    surviving only the one layout a developer happens to have.
    """
    assert ADMIN_TOOL_CONTRACT.is_file(), f"{ADMIN_TOOL_CONTRACT} does not exist"
    assert PACKAGE_ROOT in ADMIN_TOOL_CONTRACT.parents, (
        f"{ADMIN_TOOL_CONTRACT} is outside {PACKAGE_ROOT}, so it is not packaged"
    )


def test_the_contract_is_reachable_as_a_package_resource():
    """Read it the way an installed package reads its own data.

    `importlib.resources` is the mechanism that does not care whether the
    package is a checkout, a wheel, or a zipimport — which is exactly the
    variance the `__file__`-walk could not absorb.
    """
    payload = json.loads(
        files("merlins_collection").joinpath(ADMIN_TOOL_CONTRACT.name)
        .read_text(encoding="utf-8")
    )
    assert {tool["name"] for tool in payload["tools"]} == {
        "get_profit_summary",
        "find_aging_stock",
        "get_consignor_position",
        "find_pricing_outliers",
        "list_shows",
        "list_transactions",
        "list_inventory",
        "list_consignors",
        "search_admin_docs",
    }


def test_the_schemas_still_come_from_that_one_file():
    """The point of reading a contract at runtime is that there is ONE of them.

    If the fix had been to hand-write the schemas beside the file, the model's
    view could drift from what the server implements — which is the drift the
    runtime read exists to prevent. Keep the single source; just put it where
    it ships.
    """
    payload = json.loads(ADMIN_TOOL_CONTRACT.read_text(encoding="utf-8"))
    advertised = {spec["toolSpec"]["name"] for spec in _admin_tool_schemas()}
    contracted = {tool["name"] for tool in payload["tools"]}
    # The admin surface also gets the two DISPLAY tools, which are served
    # in-process by `BedrockChatService` rather than by any MCP server and so
    # appear in no contract file. Every other advertised name must come from
    # the contract, or the model has been told about a tool nothing implements.
    assert contracted <= advertised
    assert advertised - contracted == {"display_card", "set_display"}


def test_no_stray_copy_of_the_contract_remains_in_shared():
    """Two copies of a contract is worse than one in the wrong place.

    `shared/` is for values crossing the Python/TypeScript boundary. Leaving a
    duplicate there would give the next person a file to edit that nothing
    reads — the same dangling-pointer class CLAUDE.md records for
    `claude-progress.md` citations.
    """
    repo_root = Path(__file__).resolve().parents[2]
    orphan = repo_root / "shared" / "admin-tool-contract.json"
    assert not orphan.exists(), f"{orphan} still exists and nothing reads it"
