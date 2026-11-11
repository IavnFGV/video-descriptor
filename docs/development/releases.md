# Release and build procedure

Grounded in [windows-release.yml](../../.github/workflows/windows-release.yml) and
[windows_release.py](../../scripts/windows_release.py). Publication requires explicit
authorization. Preparation, tag push and workflow dispatch are not harmless checks.

## Version and BUILD

`windows-app/release-inputs.json` supplies the Windows product version;
[BUILD](../../BUILD) is the tracked integer read by local/CI builders.
`pyproject.toml` is not the Windows release version. Version-specific notes must
exist under `docs/releases/X.Y.Z.md`.

For an authorized new release, merge and validate intended source and version/notes
on main, then use **Windows release → Run workflow on main**. Its prepare job:

1. Requires main at current origin/main and an absent next build tag.
2. Increments and commits BUILD.
3. Creates annotated `vX.Y.Z-build.N` and atomically pushes main and that tag.
4. Explicitly dispatches the tagged workflow; GITHUB_TOKEN push alone does not
   provide that follow-up execution.

The product version can stay unchanged: after `0.9.2` build 3, a new preparation
creates `v0.9.2-build.4` with BUILD 4. Existing `v0.9.2` and previous build tags
are never moved or deleted. Retry the tagged workflow to retry the same source
and BUILD; run preparation on current main to build changed source.
Tagged validation requires matching product version and BUILD, a commit on
origin/main history and a BUILD greater than earlier release/build tags.
Legacy `vX.Y.Z` tags remain valid for their existing workflows. Workflow run/attempt
IDs are not the build number.

Public Full Acceptance uses `--build-qualified` packaging and gates: for example,
`VideoDescriptor-0.9.2-build.4-windows-x64.zip` and the matching `-setup.exe`.
The ZIP, installer, checksums, provenance and publisher use the same build identity.
Local packaging keeps its existing filenames unless this flag is supplied.

## Acceptance and publishing

The tagged workflow calls Full Acceptance with `windows_only=true` and downloads
accepted artifacts from that run without rebuilding. `ci_artifacts.py` enforces
standard-package policy and accepted revision. Publisher rechecks the public gate,
tag/revision, expected assets and file-size limits.

The draft contains exactly the versioned setup EXE and ZIP, `SHA256SUMS.json` and
`acceptance-provenance.json`. All four are downloaded and hash-checked before the
draft is exposed. Reruns can fill missing draft assets; existing assets are not
overwritten. Complete published releases are verified, not replaced. Unexpected
or mismatched assets stop publication.

Domestic/cached full offline installers are private regardless of filename. Local
models must not leak into standard assets. See [public policy tests](../../tests/test_public_release_policy.py),
[third-party notices](../../windows-app/THIRD-PARTY.md) and [owner constraints](safety.md).
The public gate is required, but is not a complete transitive licensing audit.

## Local builds

[Build-Local.ps1](../../scripts/Build-Local.ps1) builds committed source in an isolated
checkout. Its default cached offline profile is private, not the public standard
profile. The configured post-merge hook can queue this build and update its guarded
source preview; read [local-build.md](../local-build.md) before triggering it.
Do not bypass pinned inputs, hashes or lifecycle checks to fix an acceptance failure.

[container-release.yml](../../.github/workflows/container-release.yml) is manual;
it does not compete for native version-tag pushes. Historical combined container
publication descriptions in [CI policy](../ci-policy.md) do not define its current
trigger. See [Windows packaging](../windows-release.md),
[release readiness](../release-readiness.md) and [installed acceptance](../installed-api-acceptance.md)
for details and versioned evidence.
