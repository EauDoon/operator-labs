# Contributing

Thanks for your interest in operator-labs. Pull requests are welcome.

## Before you open a pull request

- Open an issue first for any non-trivial change so we can agree on direction.
- Keep changes focused. One logical change per pull request.
- Follow the existing code style and project layout.

## Requirements

- Tests are required for new behavior and bug fixes. Update existing tests when
  behavior changes.
- Continuous integration must be green before review. This includes lint,
  type checks, and the full test suite.
- Commits should be signed when possible and messages should follow the
  Conventional Commits style.

## Local checks

Run the same checks CI runs before pushing:

- `pnpm lint` (or the workspace equivalent)
- `pnpm test`
- `pnpm build`, where applicable

## Review process

A maintainer will review for correctness, tests, and fit with project goals.
Small fixes may be merged quickly. Larger changes go through more rounds.

## Code of conduct

Be respectful. Assume good intent. Focus on the work.
