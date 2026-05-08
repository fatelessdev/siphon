# Siphon Python Dependency Install Report

**Environment:** Python 3.14.3, Windows (win32 10.0.26200)
**Date:** 2026-05-08

## Results Summary

| Package | Status | Version | Notes |
|---|---|---|---|
| `curl_cffi` | ✅ SUCCESS | 0.15.0 | Chrome TLS impersonation — core stealth dep |
| `x_client_transaction` | ❌ NOT FOUND | N/A | No PyPI package exists. Must use a local/vendored implementation (e.g., from twitter-cli repo) |
| `pydantic` | ✅ SUCCESS | 2.13.4 | |
| `pydantic-settings` | ✅ SUCCESS | 2.14.0 | |
| `fastapi` | ✅ SUCCESS | 0.136.1 | |
| `uvicorn` | ✅ SUCCESS | 0.46.0 | |
| `click` | ✅ SUCCESS | 8.3.3 | |
| `psycopg2-binary` | ✅ SUCCESS | 2.9.12 | Had cp314 wheel available — no fallback needed |
| `apscheduler` | ✅ SUCCESS | 3.11.2 | |
| `httpx` | ✅ SUCCESS | 0.28.1 | |

### Alternative Packages (also tested)

| Package | Status | Version | Notes |
|---|---|---|---|
| `asyncpg` | ✅ SUCCESS | 0.31.0 | Async PostgreSQL driver — good alternative to psycopg2 for async-first code |

## Issues & Follow-ups

1. **`x_client_transaction` does not exist on PyPI.** The x-client-transaction-id generation logic must be sourced from the twitter-cli repo (or implemented locally). This is expected per AGENTS.md — it's a core stealth requirement with no off-the-shelf package.

2. **`psycopg2-binary` installed fine** on Python 3.14. A cp314 wheel was available. No fallback to `asyncpg` was needed, though `asyncpg` also installed successfully and is available as an async alternative.

3. **pip version warning:** pip 25.3 is installed; 26.1.1 is available. Not blocking, but worth upgrading in the project.

4. **All 9 target packages installed successfully** with no compilation errors or warnings beyond the pip version notice.

## Conclusion

9/10 packages installed successfully. The only missing package (`x_client_transaction`) has no PyPI distribution — this is expected and must be handled as a vendored/local implementation from the twitter-cli reference repo.
