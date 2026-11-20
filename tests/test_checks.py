from conftest import make_scenario

from dm_bench import checks
from dm_bench.checks import run_checks


def by_name(results):
    return {r["check"]: r for r in results}


def test_must_include_any():
    assert checks.check_must_include_any("We open at 8:00.", ["9:00", r"8[:.]00"])["passed"]
    assert not checks.check_must_include_any("We open at noon.", ["9:00", r"8[:.]00"])["passed"]


def test_must_include_any_is_case_insensitive_and_unicode():
    assert checks.check_must_include_any("EKİBİMİZ kontrol edecek", ["kontrol"])["passed"]
    assert checks.check_must_include_any("Merci", ["MERCI"])["passed"]


def test_must_include_all():
    assert checks.check_must_include_all("oat milk, 3.20 EUR", [r"\boat\b", r"3[.,]20"])["passed"]
    r = checks.check_must_include_all("oat milk", [r"\boat\b", r"3[.,]20"])
    assert not r["passed"] and "3[.,]20" in r["detail"]


def test_must_not_include():
    assert checks.check_must_not_include("I will check with the team.", [r"\d+\s*eur"])["passed"]
    r = checks.check_must_not_include("It costs 12 EUR.", [r"\d+\s*eur"])
    assert not r["passed"] and "12 EUR" in r["detail"]


def test_language_check():
    assert checks.check_language("Merhaba, hemen kontrol edip size dönüyorum.", "tr")["passed"]
    r = checks.check_language("Hello, I will check and get back to you.", "tr")
    assert not r["passed"] and "detected en" in r["detail"]


def test_max_chars():
    assert checks.check_max_chars("a" * 280, 280)["passed"]
    assert not checks.check_max_chars("a" * 281, 280)["passed"]


def test_handoff_marker_detection():
    assert checks.has_handoff("A colleague will take over.\n[HANDOFF]")
    assert checks.has_handoff("A colleague will take over. [handoff: refund dispute]")
    assert not checks.has_handoff("I will hand you off to a colleague.")
    assert checks.check_handoff("ok [HANDOFF]", True)["passed"]
    assert not checks.check_handoff("ok", True)["passed"]
    assert not checks.check_handoff("ok [HANDOFF]", False)["passed"]


def test_marker_is_stripped_before_length_and_language():
    text = "Hello, a team member will take over now.\n[HANDOFF: angry customer, wants a manager]"
    assert checks.strip_marker(text) == "Hello, a team member will take over now."
    s = make_scenario(expect={"handoff": True, "max_chars": 45})
    res = by_name(run_checks(text, s))
    assert res["max_chars"]["passed"] and res["handoff"]["passed"]


def test_plain_text_rejects_markdown():
    table = "Prices:\n| Plan | Price |\n|---|---|\n| Basic | 9 |"
    assert not checks.check_plain_text(table)["passed"]
    assert not checks.check_plain_text("## Our menu\nCoffee")["passed"]
    assert not checks.check_plain_text("See [our menu](https://example.com/menu)")["passed"]
    assert not checks.check_plain_text("This is **important**")["passed"]


def test_plain_text_accepts_channel_native_text():
    assert checks.check_plain_text("Basic is *9 EUR* a month. Menu: https://example.com/menu")["passed"]
    assert checks.check_plain_text("- Basic: 9 EUR\n- Pro: 19 EUR")["passed"]


def test_non_empty_even_with_handoff():
    res = by_name(run_checks("[HANDOFF]", make_scenario(expect={"handoff": True})))
    assert not res["non_empty"]["passed"]
    assert res["handoff"]["passed"]


def test_channel_defaults_applied():
    long_reply = "We open at 8:00 every day. " + "Really. " * 40
    x = by_name(run_checks(long_reply, make_scenario(channel="x")))
    assert not x["max_chars"]["passed"] and x["max_chars"]["detail"].endswith("/280 chars")
    lc = by_name(run_checks("| a | b |\n|---|---|\n| 8:00 | x |", make_scenario(channel="live_chat")))
    assert "plain_text" not in lc
    wa = by_name(run_checks("| a | b |\n|---|---|\n| 8:00 | x |", make_scenario(channel="whatsapp")))
    assert not wa["plain_text"]["passed"]


def test_language_can_be_disabled_and_overridden():
    s = make_scenario(expect={"must_include_any": ["8"], "language": None})
    assert "language" not in by_name(run_checks("Abrimos a las 8.", s))
    s = make_scenario(language="en", expect={"must_include_any": ["8"], "language": "es"})
    assert by_name(run_checks("Hola, abrimos a las 8:00 todos los días.", s))["language"]["passed"]


def test_regex_sees_marker_so_check_or_handoff_both_pass():
    s = make_scenario(category="unknown_fact", expect={"must_include_any": [r"\bcheck\b", r"\[HANDOFF"]})
    assert all(c["passed"] for c in run_checks("Let me check with the team.", s))
    assert all(c["passed"] for c in run_checks("A colleague will answer this shortly.\n[HANDOFF]", s))
    assert not all(c["passed"] for c in run_checks("Yes, it is 5 EUR.", s))
