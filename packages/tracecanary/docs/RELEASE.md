# TraceCanary release notes

## v0.1.1 preparation

The package version, pinned setuptools build backend, and deterministic batch report formats are the v0.1.1 release boundary. A release build must run from a clean checkout on Windows and Ubuntu with Python 3.11 or newer.

The portable Windows GUI artifact is built by
`.github/workflows/portable-windows.yml`. The workflow installs the exact
package and PyInstaller versions, builds `TraceCanary.pyw` in windowed mode,
archives the executable, and writes a SHA-256 sidecar.

The workflow retains the archive and sidecar as run artifacts for 14 days. It
does not create a GitHub Release or publish the files automatically.

Before a maintainer creates a tag, run the full unit suite, the CLI smoke check,
the GUI smoke check, and the batch SARIF and JUnit checks. Verify the downloaded
archive against its sidecar. Remote publication and release creation remain
separate approved actions.
