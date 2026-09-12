# Release checklist (owner execution; nothing here is done by the developer)

- [ ] Owner approves the PRs on this branch (see PROGRESS.md for the list).
- [ ] Owner reviews RELEASE-NOTES.md and edits the final framing.
- [ ] Decide version increments for both packages (currently 0.2.0; the new
      features justify a 0.3.0 — owner decision).
- [ ] Owner merges the PRs (developer never merges own work).
- [ ] Tag releases only from `main` after CI is green there
      (`corridor-lab-v0.x.y`, `tracecanary-v0.x.y`); the portable Windows
      GUI workflows trigger on their tags automatically.
- [ ] Do not publish to any package index unless the owner separately
      authorizes it; the repository has no publishing workflow by design.
- [ ] After tagging, verify the Windows portable artifacts build and their
      SHA-256 files are attached.
- [ ] Record the final release state in PROGRESS.md.
