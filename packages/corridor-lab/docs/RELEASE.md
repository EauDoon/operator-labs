# Corridor Lab release notes

## v0.1.1 preparation

Version 0.1.1 pins the setuptools build backend and adds bounded batch portfolios, explicit two-parameter stress grids, and a Pareto frontier that keeps expected recipient amount and expected sender cost separate.

The portable Windows GUI workflow is `.github/workflows/portable-windows.yml`.
It builds the windowed `CorridorLab.pyw` launcher with pinned tools, writes a
SHA-256 sidecar, and retains both files as run artifacts for 14 days. The
workflow does not create or publish a remote release. A maintainer must run the
full tests, GUI smoke check, and report format checks, then verify the downloaded
archive against its sidecar before separately approving publication.
