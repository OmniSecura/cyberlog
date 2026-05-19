# Contributing

Thanks for taking the time to look at cyberlog! This file is a quick map
for anyone wanting to fix a bug, add a feature, or audit the package.

## Project layout

```
cyberlog/
  __init__.py        public API re-exports
  _version.py        single source of truth for the package version
  core.py            CyberLogCore — the only class users see
  buffer.py          in-memory queue + background flush thread
  transport.py       HTTP layer (httpx) + response classifier
  models.py          CyberLogEntry dataclass
  exceptions.py      error hierarchy
tests/               pytest suite (no network access required)
```

## Development workflow

```bash
git clone https://github.com/OmniSecura/cyberlog-python.git
cd cyberlog-python

python -m venv venv && source venv/bin/activate   # or `venv\Scripts\activate` on Windows
pip install -e ".[dev]"

# Run tests
pytest -q

# Lint
ruff check cyberlog tests
```

CI runs the same commands on Python 3.9–3.13 for every PR.

## Releasing (maintainers only)

1. Bump `cyberlog/_version.py` and add an entry to `CHANGELOG.md`.
2. Commit on `main`.
3. Tag the release: `git tag v0.2.0 && git push origin v0.2.0`.
4. The `Publish to PyPI` workflow builds the sdist + wheel and publishes via
   PyPI Trusted Publishing. No secret tokens involved.

## Pull-request checklist

* [ ] New behaviour has tests in `tests/`.
* [ ] `pytest -q` passes locally.
* [ ] `ruff check cyberlog tests` is clean.
* [ ] Public API changes are documented in `README.md` and `CHANGELOG.md`.
* [ ] No network calls in unit tests — use the `FakeTransport` fixture in
      `tests/conftest.py` or `httpx.MockTransport`.
