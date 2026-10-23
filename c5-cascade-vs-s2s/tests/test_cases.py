from voice_bench import cli, support

TOOL_NAMES = {t.id if hasattr(t, "id") else t.__name__ for t in support.TOOLS}


def test_tool_names():
    assert TOOL_NAMES == {"get_order_status", "find_customer_orders", "log_action", "update_order_status"}


def test_cases_are_well_formed():
    cases = cli.load_cases()
    assert len({c["id"] for c in cases}) == len(cases) == 15
    for c in cases:
        assert c["question"] and c["facts"], c["id"]
        assert set(c["expected_tools"]) <= TOOL_NAMES, c["id"]
        assert set(c.get("forbidden_tools", [])) <= TOOL_NAMES, c["id"]
        assert not set(c["expected_tools"]) & set(c.get("forbidden_tools", [])), c["id"]


def test_security_cases_say_what_must_never_be_spoken():
    for c in cli.load_cases():
        if c["category"].startswith("security") or c["category"] == "pii_spoken":
            assert c.get("must_not_say"), c["id"]


def test_case_filter():
    assert [c["id"] for c in cli.load_cases("q12,q01")] == ["q01", "q12"]
