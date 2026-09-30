"""Issue #63: a `!secret` address written into the backend call as Jinja quotes.

The emitted value is Jinja inside YAML, so `dump_pinned` quoting the
artifact's scalar says nothing about whether the call *inside* that scalar
parses. These cases read the emitted call back under Jinja's own
string-literal rules (`_lookup_arguments` below), which is the whole
assertion: the call tokenises as one `lookup()`, and each argument decodes to
exactly what went in.
"""

from __future__ import annotations

import pytest
import yaml

from reverie.yaml_io import dump_jinja_literal
from tests.conftest import run_reverie

_CALL_OPEN = "{{ lookup("
_CALL_CLOSE = ") }}"


def _decode_jinja_string(literal: str) -> str:
    """One single-quoted Jinja string literal, back to the text it stands for.

    Jinja processes backslash escapes inside a string literal the way Python
    does, so unescaping is the mirror of the two substitutions the emitter
    makes -- and a literal the emitter closed early would never have arrived
    here as one argument to begin with.
    """

    body = literal[1:-1]
    out = []
    index = 0
    while index < len(body):
        if body[index] == "\\":
            out.append(body[index + 1])
            index += 2
        else:
            out.append(body[index])
            index += 1
    return "".join(out)


def _lookup_arguments(call: str) -> tuple[list[str], dict[str, str]]:
    """The positional and keyword arguments of an emitted `lookup()` call.

    Splits on the commas *outside* a string literal, so an apostrophe the
    emitter failed to escape shows up here as a split in the wrong place or
    an unterminated literal rather than as a silent pass.
    """

    assert call.startswith(_CALL_OPEN) and call.endswith(_CALL_CLOSE), call
    inner = call[len(_CALL_OPEN) : -len(_CALL_CLOSE)]

    pieces: list[str] = []
    current = ""
    in_string = False
    index = 0
    while index < len(inner):
        char = inner[index]
        if in_string and char == "\\":
            current += inner[index : index + 2]
            index += 2
            continue
        if char == "'":
            in_string = not in_string
        if char == "," and not in_string:
            pieces.append(current)
            current = ""
            index += 1
            continue
        current += char
        index += 1
    assert not in_string, f"unterminated string literal in {call}"
    pieces.append(current)

    positional: list[str] = []
    keywords: dict[str, str] = {}
    for piece in (piece.strip() for piece in pieces):
        if piece.startswith("'"):
            positional.append(_decode_jinja_string(piece))
        else:
            name, _, literal = piece.partition("=")
            keywords[name] = _decode_jinja_string(literal)
    return positional, keywords


def _declare_backend(
    source, lookup: str = "community.hashi_vault.hashi_vault", options=None
) -> None:
    reverie_yml = source / "reverie.yml"
    block = {
        "secret_backend": {
            "lookup": lookup,
            "options": options if options is not None else {"url": "https://vault.example"},
        }
    }
    reverie_yml.write_text(
        reverie_yml.read_text(encoding="utf-8") + yaml.safe_dump(block, sort_keys=False),
        encoding="utf-8",
        newline="",
    )


def _write_secret(source, address: str) -> None:
    # Single-quoted YAML, so the layer file carries the address verbatim: the
    # one escape a single-quoted scalar has is `''` for an apostrophe, and a
    # backslash in it is a backslash.
    quoted = "'" + address.replace("'", "''") + "'"
    (source / "roles" / "web.yml").write_text(
        "settings: {timeout: 60}\n"
        "nested: {a: {x: 99}, c: 3}\n"
        f"pw: !secret {quoted}\n",
        encoding="utf-8",
        newline="",
    )


def _compiled_secret(source) -> str:
    artifact = yaml.safe_load((source / "host_vars" / "host1.yml").read_text(encoding="utf-8"))
    return artifact["reverie"]["pw"]


# The four characters the ticket names, one address each: an apostrophe closes
# a string literal early, a backslash eats whatever follows it, and `{{`/`}}`
# nest a template inside the template.
_HOSTILE_ADDRESSES = [
    pytest.param("secret/data/it's/a", id="apostrophe"),
    pytest.param("secret\\data\\password", id="backslash"),
    pytest.param("secret/data/a{{trap}}", id="braces"),
    pytest.param("secret/data/}}{{", id="unbalanced-braces"),
    pytest.param("secret/it's\\a{{trap}}", id="all-four"),
]


@pytest.mark.parametrize("address", _HOSTILE_ADDRESSES)
def test_hostile_address_survives_into_a_call_that_parses(fixture_dir, address):
    source = fixture_dir("merge")
    _declare_backend(source)
    _write_secret(source, address)

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    positional, _keywords = _lookup_arguments(_compiled_secret(source))
    assert positional == ["community.hashi_vault.hashi_vault", address]


@pytest.mark.parametrize("lookup", ["it's.a.lookup", "back\\slash", "a{{trap}}"])
def test_hostile_lookup_name_is_quoted_too(fixture_dir, lookup):
    source = fixture_dir("merge")
    _declare_backend(source, lookup=lookup)
    _write_secret(source, "prod/svc#token")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    positional, _keywords = _lookup_arguments(_compiled_secret(source))
    assert positional == [lookup, "prod/svc#token"]


@pytest.mark.parametrize("option", ["it's", "back\\slash", "a{{trap}}", "}}"])
def test_hostile_option_value_is_quoted_too(fixture_dir, option):
    source = fixture_dir("merge")
    _declare_backend(source, options={"url": option})
    _write_secret(source, "prod/svc#token")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    _positional, keywords = _lookup_arguments(_compiled_secret(source))
    assert keywords == {"url": option}


def test_option_quoting_is_jinja_not_python_repr(fixture_dir):
    """Python's `repr` switches to double quotes rather than escape a `'`.

    Jinja accepts either, but Python's scheme is not the scheme the address
    and the lookup name are written under, and the divergence is not
    something a reader of the emitted call should have to know about -- so
    one rule writes the whole call.
    """

    source = fixture_dir("merge")
    _declare_backend(source, options={"url": "it's"})
    _write_secret(source, "prod/svc#token")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    assert "url='it\\'s'" in _compiled_secret(source)


def test_non_string_option_values_are_jinja_literals(fixture_dir):
    # `configure` holds `options` to being a map and says nothing about the
    # shape of a value in it, so every type the closed domain has can arrive
    # here -- a collection included, which has a Jinja literal of its own
    # rather than being written as the text of itself.
    source = fixture_dir("merge")
    _declare_backend(
        source,
        options={"verify": False, "retries": 3, "token": None, "hosts": ["a", "it's"]},
    )
    _write_secret(source, "prod/svc#token")

    result = run_reverie("compile", str(source))

    assert result.returncode == 0, result.stderr
    call = _compiled_secret(source)
    assert "verify=false" in call
    assert "retries=3" in call
    assert "token=none" in call
    assert "hosts=['a', 'it\\'s']" in call


@pytest.mark.parametrize(
    "value,expected",
    [
        ("plain", "'plain'"),
        ("it's", r"'it\'s'"),
        ("back\\slash", r"'back\\slash'"),
        ("a{{trap}}", "'a{{trap}}'"),
        ("}}", "'}}'"),
        (True, "true"),
        (False, "false"),
        (None, "none"),
        (7, "7"),
        (1.5, "1.5"),
        # Jinja has no literal for either, so they read as text rather than
        # as a name the expression would fail on.
        (float("inf"), "'inf'"),
        (float("nan"), "'nan'"),
        (["a", "it's"], r"['a', 'it\'s']"),
        ({"b": 1, "a": "x"}, "{'a': 'x', 'b': 1}"),
    ],
)
def test_dump_jinja_literal(value, expected):
    assert dump_jinja_literal(value) == expected
