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

## PR check: version must change

For every **pull request targeting `main`**, CI runs a check that the version in `pyproject.toml` is **different** from the version on `main`. If it is the same, the check fails and reminds you to bump the version (e.g. `uv version --bump patch`) before merging. That way you don’t merge without a version bump.

## Summary

- **You** update the version in **`pyproject.toml`** for every release (patch, minor, or major).
- Open a PR to `main`; CI will fail the “version changed” check until the version is updated.
- After you merge to `main`, CI tags that version and publishes to PyPI and the container registry.
