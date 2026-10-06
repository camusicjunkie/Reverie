# Coding standards

Judgement calls a reviewer applies to a diff. Mechanical rules live in checks,
not here: ruff (`pyproject.toml`: line length, import order,
`from __future__ import annotations` in every module), `tests/test_house_style.py`
(ASCII-only Python source), `tests/test_spec_registry.py` and `tests/conftest.py`
(registry shape, generated docs current, every implemented error id fixtured).

## Docstrings carry the why

A module, class or function docstring explains why the code is shaped the way
it is: the rule it enforces, the ADR or CONTEXT.md term it rests on, the case it
exists to keep distinct. Restating what the next line does is noise. When a diff
changes behaviour, every docstring in the touched hunks still describes the new
behaviour; a half-updated docstring is a finding.

## One home per explanation

A concept is explained once, in its natural home: a domain term in `CONTEXT.md`,
a decision in `docs/adr/`, a vocabulary entry in `spec/*.yml`. Code docstrings
cite that home in a clause rather than re-telling it. The same paragraph near-
verbatim in CONTEXT.md, a module docstring and a spec entry will drift; flag it.

## Domain vocabulary

Names, test names and diagnostics use the terms defined in `CONTEXT.md`, and
avoid the synonyms its `_Avoid_:` lines list. A concept the glossary lacks is a
gap to raise, not a word to invent.

## Issue citations

In code and test docstrings, cite an issue as `issue #NN`. The "name the ticket
as a link" rule in `docs/agents/issue-tracker.md` governs tracker prose and
human-facing narration, not source.

## Phase ownership

A diagnostic is raised in the phase that owns its condition, under that phase's
id prefix (`configure.`, `load.`, `enumerate.`, ...). Shared mechanics modules
(`reverie_yml.py`, `yaml_io.py`, `keypath.py`) know mechanics, not schema: they
name no condition and decide no shape.

## Tests

Shared test helpers live in `tests/conftest.py`; a helper copied into a second
test module is a finding. A test asserts the diagnostic by id and fields through
`assert_diagnostic`, driving the real CLI via `run_reverie` where the behaviour
is user-visible.
