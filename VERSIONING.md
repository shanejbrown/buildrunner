# Versioning

The **source of truth** for the version is `pyproject.toml` → `[project]` → `version`.  
You are responsible for updating it for every release. CI tags and publishes whatever version is on `main` when you push.

## Where to update version

- **Single place:** `pyproject.toml` — set `version = "X.Y.Z"` (e.g. `"3.22.0"`). You can use `uv version 3.22.0` or `uv version --bump patch` (etc.) and commit the change.

## Releasing (patch, minor, or major)

| You want | What to do |
|----------|------------|
| **Patch** (e.g. 3.22.0 → 3.22.1) | Run `uv version --bump patch` (or set `version = "3.22.1"` in `pyproject.toml`). Commit, open a PR to `main`, merge. CI will tag and publish. |
| **Minor** (e.g. 3.22 → 3.23.0) | Run `uv version 3.23.0` or `uv version --bump minor`. Commit, open a PR to `main`, merge. CI will tag and publish. |
| **Major** (e.g. 3.x → 4.0.0) | Set `version = "4.0.0"` in `pyproject.toml` (or `uv version 4.0.0`). Commit, open a PR to `main`, merge. CI will tag and publish. |

## PR check: version must increase

For every **pull request targeting `main`**, CI runs a check that the version in `pyproject.toml` is **strictly greater** than the version on `main`: at least one of major.minor.patch must increase, and none may decrease (except MINOR/PATCH may reset when MAJOR increases, or PATCH when MINOR increases). MAJOR may never decrease; MINOR may not decrease unless MAJOR increased; PATCH may not decrease unless MAJOR or MINOR changed. If the version is unchanged or violates these rules, the check fails.

## Summary

- **You** update the version in **`pyproject.toml`** for every release (patch, minor, or major).
- Open a PR to `main`; CI will fail the “version changed” check until the version is updated.
- After you merge to `main`, CI tags that version and publishes to PyPI and the container registry.
