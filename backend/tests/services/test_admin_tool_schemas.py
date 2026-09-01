"""RED for the admin analyst chat's 'all time' failure (owner report 2026-08-28).

Asked "what is our most profitable show? / All time", the analyst repeatedly
demanded exact `start`/`end` dates instead of computing the full-history range
itself. The root cause was not the model being unhelpful — it was that
`_admin_tool_schemas()` built every property as a bare `{}`:

    {"properties": {p: {} for p in tool["properties"]}}

So the model was told a parameter named "start" exists and NOTHING about what
it means, whether it is required, or that omitting it is even possible. The
docstring on `_admin_tool_schemas()` already claimed "the admin tools carry
their descriptions... where the contract test can see them" — a claim that
was never true in practice, because `admin-tool-contract.json` had no
`description` field on any tool or property. These tests pin the fix: real
descriptions reach the model, and `get_profit_summary`'s bounds are optional.
"""

from merlins_collection.services.bedrock import _admin_tool_schemas

_DISPLAY_TOOLS = {"display_card", "set_display"}


def _schema_for(name: str) -> dict:
    return next(
        s["toolSpec"] for s in _admin_tool_schemas() if s["toolSpec"]["name"] == name
    )


def test_every_admin_tool_has_a_real_description_not_the_auto_generated_stub():
    for spec in _admin_tool_schemas():
        name = spec["toolSpec"]["name"]
        if name in _DISPLAY_TOOLS:
            continue  # served in-process, described elsewhere, not from the contract
        description = spec["toolSpec"]["description"]
        assert description, f"{name} has no description at all"
        assert description != name.replace("_", " "), (
            f"{name} fell back to the auto-generated name-shaped stub"
        )


def test_every_admin_tool_property_carries_a_real_description():
    for spec in _admin_tool_schemas():
        name = spec["toolSpec"]["name"]
        if name in _DISPLAY_TOOLS:
            continue
        props = spec["toolSpec"]["inputSchema"]["json"]["properties"]
        for prop_name, prop_schema in props.items():
            assert prop_schema.get("description"), (
                f"{name}.{prop_name} has no description — the model is told a "
                "parameter exists and nothing about what it means"
            )


def test_get_profit_summary_dates_are_optional_so_all_time_needs_no_literal_dates():
    """THE fix. Omitting both dates must be a valid call, not a guessing game."""
    schema = _schema_for("get_profit_summary")
    required = schema["inputSchema"]["json"]["required"]
    assert "start" not in required
    assert "end" not in required


def test_find_pricing_outliers_direction_is_constrained_to_its_three_values():
    schema = _schema_for("find_pricing_outliers")
    direction_schema = schema["inputSchema"]["json"]["properties"]["direction"]
    assert set(direction_schema.get("enum", [])) == {"over", "under", "unpriced"}
