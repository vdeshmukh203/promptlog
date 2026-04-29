# Contributing to promptlog

Thank you for your interest in contributing!

## Setting up a development environment

```bash
git clone https://github.com/vdeshmukh203/promptlog.git
cd promptlog
pip install -e ".[dev]"
```

## Running the test suite

```bash
pytest tests/ -v
```

All tests must pass before opening a pull request. The suite covers:
- Hash-chain logging and verification (`tests/test_promptlog.py`)
- HTTP interception across OpenAI, Anthropic, and Google providers (`tests/test_intercept.py`)

## Code style

- Follow PEP 8. Lines should be ≤ 100 characters.
- All public functions must have type annotations.
- Add or update tests for any new behaviour.
- Keep `dependencies = []` in `pyproject.toml`; the library must stay zero-dependency (stdlib only).

## Reporting bugs

Open an issue on GitHub describing:
1. The Python version and OS.
2. The exact steps to reproduce the problem.
3. What you expected to happen vs. what actually happened.

## Feature requests

Open an issue tagged `enhancement` before writing code so we can discuss the design.

## Pull request checklist

- [ ] `pytest tests/ -v` passes locally
- [ ] New behaviour is covered by a test
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`
- [ ] Commit messages are clear and imperative ("Fix X", "Add Y")

## Licence

By contributing you agree that your changes will be released under the
[MIT Licence](LICENSE).
