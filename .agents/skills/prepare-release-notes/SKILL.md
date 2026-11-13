---
name: prepare-release-notes
description: Prepare Video Descriptor Windows release notes while preserving changes from unpublished builds.
---

# Prepare release notes

Use when writing or updating the next Windows build's release notes. Follow
`docs/development/releases.md`; preparing notes does not authorize publishing,
creating tags, changing BUILD or dispatching a release.

## Rules

1. **Carry forward unpublished changes.** Check which Windows build was last
   actually published and review the versioned notes of subsequent unpublished
   builds. Include all still-applicable user-facing changes from those builds in
   `docs/releases/next-build.md`, along with new changes. Preserve any existing
   prepared notes; do not modify frozen notes or move old tags. Describe changes
   and their practical effect on users, correcting obsolete wording. Do not include
   test procedures, passed or failed tests, CI, or internal release history in
   public notes; keep those details in development evidence instead. A tag or a
   prepared build alone is not proof of publication; if publication status cannot
   be verified, say so to the owner rather than guessing.
