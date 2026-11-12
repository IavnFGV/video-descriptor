---
name: review-release-readiness
description: Review Video Descriptor Windows release readiness, BUILD handling, acceptance provenance and public artifact boundaries without publishing a release.
---

Read [release procedure](../../../docs/development/releases.md) and
[owner constraints](../../../docs/development/safety.md). Use this for release/CI
failure investigation or readiness assessment, not implicit publication permission.

From the repository root, trace `.github/workflows/windows-release.yml`,
`scripts/windows_release.py`, `scripts/ci_artifacts.py` and relevant
`full-acceptance.yml` jobs. Check ref, `windows-app/release-inputs.json`, tracked
BUILD, the release notes of that build and exact accepted revision. Notes of the
next build are prepared in `docs/releases/next-build.md` and frozen into the
tagged commit as `docs/releases/X.Y.Z-build.N.md`; publication reads them from
that commit. Distinguish workflow/tool/download failures from application/model
failures before repeating an expensive run.

Never invoke `windows_release.py prepare` as a check: it commits BUILD, creates
and pushes a tag and dispatches publication. Never bump BUILD for an existing-tag
rerun. `windows_release.py next-notes` only writes the local notes template; it
creates no commit, tag or push. Do not upload Domestic/cached installers or
bypass the public gate by renaming files. Preserve accepted hashes; rebuilt bytes
need their own acceptance.

Use focused `tests/test_windows_release.py`, `tests/test_public_release_policy.py`
and `tests/test_release_packaging.py`, plus local Fast checks as appropriate.
Inspect provenance without exposing secrets/private model artifacts. Report missing
installer, CPU, real NPU/GPU and model-behavior evidence separately. Publication
remains an explicitly authorized action; this skill grants no remote permission.
