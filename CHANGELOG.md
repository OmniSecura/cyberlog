# Changelog

All notable changes to **cyberlog** are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] — Unreleased

Initial release.

### Added
- `CyberLogCore` client with `debug`/`info`/`warning`/`error`/`critical` methods.
- Sticky-context child loggers via `bind(**fields)`.
- Non-blocking in-memory buffer with background flush thread.
- Batched delivery with exponential backoff retries and HTTP-413 split-and-retry.
- Startup API-key validation via `GET /api/v1/auth/validate`.
- `atexit` flush hook and explicit `flush()` / `close()` / context-manager support.
- Console-echo mode (`console=True`) for local development.
- Full type hints and `py.typed` marker for IDE / mypy support.
