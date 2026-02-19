# Versioning

The **source of truth** for the version is `pyproject.toml` → `[project]` → `version`.  
CI uses that value and the resulting git tag as the release version.

## Where to update version

- **Single place:** `pyproject.toml` — set `version = "X.Y.Z"` (e.g. `"3.21"` or `"3.21.0"`).

## How versions are produced

| You want | What to do |
|----------|------------|
| **Patch** (e.g. 3.21.0 → 3.21.1) | Nothing. Push to `main`; CI bumps patch, commits it, tags that version, and publishes. |
| **Minor** (e.g. 3.21 → 3.22.0) | Update version in `pyproject.toml` (e.g. `uv version 3.22.0` or `uv version --bump minor`). Commit with message **`Release 3.22.0`** and merge to `main`. CI will use that version as-is (no bump), tag it, and publish. |
| **Major** (e.g. 3.21 → 4.0.0) | Same as minor: set `version = "4.0.0"` in `pyproject.toml`, commit **`Release 4.0.0`**, merge to `main`. |

## Summary

- **Track/update** major.minor.patch in **`pyproject.toml`**.
- **Patch releases:** automatic on every push to `main` (CI bumps and commits).
- **Minor/major releases:** set the version in `pyproject.toml` and use a commit message starting with **`Release X.Y.Z`** so CI does not bump again and tags that version.
