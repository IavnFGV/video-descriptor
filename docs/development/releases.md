# Release and build procedure

Grounded in [windows-release.yml](../../.github/workflows/windows-release.yml) and
[windows_release.py](../../scripts/windows_release.py). Publication requires explicit
authorization. Preparation, tag push and workflow dispatch are not harmless checks.

## Version and BUILD

`windows-app/release-inputs.json` supplies the Windows product version;
[BUILD](../../BUILD) is the tracked integer read by local/CI builders.
`pyproject.toml` is not the Windows release version.
Starting with build 12, release identifiers use at least four digits: `0012` in
BUILD, tags, build-specific notes, artifact filenames and displayed labels. Older
unpadded tags and artifacts remain unchanged and valid for retries. Comparisons
remain numeric. Already installed builds whose update checker predates this change
cannot discover padded tags automatically; their users must open the release page.

## Release notes of a build

Every build has its own release notes. The next BUILD number is not needed:
developers write the notes of the upcoming build in
[docs/releases/next-build.md](../../docs/releases/next-build.md) during ordinary
development and merge that file to main before a release.

1. Write or update `docs/releases/next-build.md` and merge it to main.
2. Release with **Windows release → Run workflow on main**. Preparation resolves
   the next BUILD, copies the prepared notes verbatim into
   `docs/releases/X.Y.Z-build.N.md`, consumes `next-build.md` and commits both
   with the incremented BUILD in the tagged commit `vX.Y.Z-build.N`.
3. Publication reads the notes from that tagged commit, so retrying an older tag
   never reuses the notes of a newer commit. Earlier release notes and the legacy
   version notes `docs/releases/X.Y.Z.md` stay valid for `vX.Y.Z` tags.
4. After a published release, run `python scripts/windows_release.py next-notes`
   to write the template of the following build. That command only writes the
   local file: no commit, no tag and no push. Edit the file, commit it on a task
   branch and merge it to main before the next preparation.

Preparation refuses empty, template or repeated notes and leaves BUILD unchanged.

For an authorized new release, merge and validate intended source and version/notes
on main, then use **Windows release → Run workflow on main**. Its prepare job:

1. Requires main at current origin/main and an absent next build tag.
2. Requires prepared release notes in `docs/releases/next-build.md`.
3. Increments and commits BUILD together with the notes of that build.
4. Creates annotated `vX.Y.Z-build.N` and atomically pushes main and that tag.
5. Explicitly dispatches the tagged workflow; GITHUB_TOKEN push alone does not
   provide that follow-up execution.

The product version can stay unchanged: after `0.9.4` build 11, a new preparation
creates `v0.9.4-build.0012` with BUILD 0012. Existing `v0.9.2` and previous build tags
are never moved or deleted. Retry the tagged workflow to retry the same source
and BUILD; run preparation on current main to build changed source. A retry does
not increment BUILD, does not overwrite a published release and does not change
the recorded notes. Tagged validation requires matching product version and BUILD,
a commit on origin/main history, a BUILD greater than earlier release/build tags
and usable release notes in the tagged commit.
Legacy `vX.Y.Z` tags remain valid for their existing workflows. Workflow run/attempt
IDs are not the build number.

Public Full Acceptance uses `--build-qualified` packaging and gates: for example,
`VideoDescriptor-0.9.4-build.0012-windows-x64.zip` and the matching `-setup.exe`.
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
or mismatched assets stop publication. The release description is the notes of the
tagged commit; a release whose description differs from them is reported instead
of being rewritten.

Only the standard installer profile ships. Local models must not leak into standard
assets. See [public policy tests](../../tests/test_public_release_policy.py),
[third-party notices](../../windows-app/THIRD-PARTY.md) and [safety constraints](safety.md).
The public gate is required, but is not a complete transitive licensing audit.

## Local builds

[Build-Local.ps1](../../scripts/Build-Local.ps1) builds committed source in an isolated
checkout using the single standard profile; the former `-Domestic`/`--cached` offline
profiles were removed. The configured post-merge hook can queue this standard build and
update its guarded source preview; read [local-build.md](../local-build.md) before
triggering it, including the current checkout-specific `.venv` guard conflict on
Windows. This is not a claim of a successful end-to-end build at current HEAD.
Do not bypass pinned inputs, hashes or lifecycle checks to fix an
acceptance failure.

[container-release.yml](../../.github/workflows/container-release.yml) is manual;
it does not compete for native version-tag pushes. The remaining semantic-tag
combined publisher and its limitations are described in [CI policy](../ci-policy.md).
See [Windows packaging](../windows-release.md),
[release readiness](../release-readiness.md) and [installed acceptance](../installed-api-acceptance.md)
for details and versioned evidence.
