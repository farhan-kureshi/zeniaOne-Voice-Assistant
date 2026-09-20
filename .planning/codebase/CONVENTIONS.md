# Code Conventions

## Code Formatting
- Code is formatted using `black` (line length = 100).
- Linting is managed using `ruff` (target version Py3.10).
- Static type checking is configured with `mypy` (with `warn_return_any` and `warn_unused_configs` enabled).

## General Principles
- Environment variables should be managed through `.env` and loaded securely (e.g. `pydantic-settings`).
- Hardcoded sensitive data is forbidden.
- Async Python (`async`/`await`) is used extensively for I/O operations (WebSockets, DB calls) to ensure high concurrency without blocking the event loop.
