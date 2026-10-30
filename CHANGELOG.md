# Changelog

All notable changes to Operator Labs (Corridor Lab and TraceCanary) are
documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file consolidates content previously split across `RELEASE-NOTES.md`
(release drafts) and `PROGRESS.md` (development status). Both source files
are now deprecated; see the deprecation note at the top of each.

## [Unreleased]

### Added

#### Corridor Lab

- **`project refresh` accepts deliberately edited inputs.** After a
  deliberate edit to a project input, every project command refused the
  project as changed since it was saved, and nothing could accept the change
  short of hand-editing SHA-256 values or rebuilding the project.
  `corridorlab project refresh DIR --input LABEL` (`scenario`, `routes`,
  `baseline`, or `variant:NAME` for a file variant; repeatable) validates each
  named input with its own loader, re-checks the merged scenario when saved
  routes stand in for embedded ones, and records the new fingerprints only
  when the project then loads with no problems. Otherwise it exits 2, lists
  every blocking problem (unnamed modified or missing inputs included), and
  leaves the manifest byte-identical. Derived variants that no longer apply
  are named as warnings. Refresh validates content, which `project create`
  does not: it is the stricter, explicit acceptance.
- **`--evidence FILE` on `project run`, `run-variants`, `compare-variants` and
  `show-variant`.** The evidence document embeds the report, names the
  manifest's relative scenario path, the saved routes when they stand in, and
  the manifest path, and adds an optional `inputs.project_inputs` list with
  the label, path, verified SHA-256 and folder flag of every manifest input.
  The desktop **Export Evidence...** adds the same list while a project is
  open. Destinations are checked against every project input, the project
  directory and each other before anything is computed. Standalone evidence
  is unchanged.

#### TraceCanary

- **`campaign run` writes reports and evidence.** New `--format json|human`,
  `--output FILE` and `--save-evidence FILE`. The human view is the shared
  value-free renderer, and the evidence document is the
  `tracecanary.evidence/v1` document the desktop **Save Evidence As...**
  writes (now built by one shared function, so desktop bytes are unchanged).
  `--output`, `--save-summary` and `--save-evidence` must name different files
  outside the project and batch directories, none of them an input, and are
  checked before the campaign runs; every requested text is checked against
  the canary values before anything is printed or written.
- **`campaign compare --fail-on-regression`** adds a gate verdict with
  value-free reasons (a worse campaign or phase status, a phase that stopped
  running, a new finding code, or a higher count for a persistent code) and
  exits 0 pass, 1 regression, 2 unresolved candidate. Without the flag the
  comparison output and exit status are unchanged.
- **`project refresh` accepts deliberately edited inputs.**
  `tracecanary project refresh PROJECT --input LABEL` (`contract`, `input`,
  `baseline`, `candidate` or `batch`) validates each named input (the contract
  must load, inputs and candidates must be structurally valid exports, a
  baseline must satisfy the contract, a batch folder must enumerate within its
  bounds) and records the new fingerprints only when the project then loads
  with no problems. It prints labels, paths and `refreshed` or `unchanged`,
  never a digest of a canary-bearing file, and warns when a refreshed contract
  no longer accepts the saved baseline.

### Fixed

- **Both packages: project inputs that resolve outside the project.**
  `project create` refuses inputs outside the project directory, but loading a
  project followed a junction or symlinked directory inside it, and on Windows
  resolved a drive-relative reference such as `C:outside/scenario.json`
  against the working directory, so such a project validated. These inputs
  are now reported as problems by `project validate`, `open`, `run`,
  `campaign run` and the desktop **Open Project...** (exit 2).
- **Both packages: a failed `project create` blocked its own retry.** A create
  that failed after copying inputs (an invalid project id, an invalid
  threshold, a name collision) left the copies in `inputs/`, and the corrected
  retry then failed with "project input already exists". Settings that need no
  input are now validated before anything is copied, and a failure before the
  manifest is written, from the CLI or the desktop save, removes exactly the
  files and folders that attempt created. Pre-existing files are never touched.
- **Corridor Lab: saved routes were ignored when the scenario embeds none.**
  `project create --routes` copied and fingerprinted a route selection that no
  project command read, so a project laid out like `examples/fictional-corridor`
  validated while `project run` reported every experiment unresolved and
  `compare-variants` exited 2. Project commands and the desktop now use the
  saved routes in that case; scenarios that embed routes behave exactly as
  before, and the scenario file is never rewritten.
- **Corridor Lab: variant commands on an invalid project scenario.**
  `show-variant` crashed with a Python traceback (exit 1) on a scenario that is
  not an object and printed a diff for an incomplete one, and `add-variant`
  saved variants onto either. `show-variant`, `compare-variants` and
  `add-variant` now validate the project scenario first and exit 2 with the
  validator's message.
- **Corridor Lab: `add-variant` saved variants the desktop rejects.** Changes
  such as `transaction.send_amount=-5` or a route the scenario does not have
  used to print `variant saved` and then made `compare-variants` exit 2 for the
  whole project. The derived scenario is now validated before the manifest is
  written, as the desktop does; such variants exit 2 and are not saved.
- **Corridor Lab: `show-variant --output tight.json` wrote Markdown.** An
  `--output` ending in `.json` now gives JSON; an explicit `--format` still
  wins, and Markdown stays the default otherwise.
- **TraceCanary: half a population gate was dropped silently.** `batch` and
  `coverage-batch` with only `--population-minimum` passed where a full gate
  failed, `project create --population-minimum` alone saved no gate, and
  `campaign run` with one half ran without a population-gate phase. A gate now
  needs both a scope and a minimum on every CLI and library surface; half a
  gate exits 2. Saved manifests could never hold half a gate, so no saved
  project changes outcome.
- **TraceCanary: `campaign compare` ignored the batch per-file threshold.**
  Summaries from campaigns with batch thresholds 0 and 1 compared as
  `pass -> pass`, contrary to the README. Campaigns and summaries now record
  `coverage.batch_minimum_ratio` (null without a batch phase), and differing
  values are unsupported (exit 2). A summary saved by 0.3.0 has no such key,
  which counts as null: it still compares with a new summary whose campaign
  had no batch threshold, and is unsupported against one that had a threshold.
- **TraceCanary: contract review missed canary values that clash with report
  wording.** Values such as `TC004`, `coverage-gate`, `retention-matrix` and
  `required-0001` reviewed as pass, yet each withholds real reports. The review
  vocabulary now covers every report mode, every finding code, and real reports
  with findings from every checker and output format, plus identifiers
  numbered per draft. Contracts that passed review before can now report such
  conflicts.
- **TraceCanary desktop: contract review read up to 5 MB.** Every other
  contract loader caps at 1 MB and nesting depth 50; desktop review now uses
  the same limits, and CLI review now accepts the loader's depth 50 instead
  of 32.
- **TraceCanary desktop: Run Campaign after Open Project ignored the saved
  settings.** Opening a project filled a 0.95 ratio and a `span >= 1` gate the
  project never saved, copied the candidate ratio into the batch-ratio entry,
  and never passed a batch ratio to the campaign, so the desktop campaign and
  its summaries differed from `campaign run PROJECT`. The entries now hold the
  saved values (blank when nothing was saved) and the campaign applies the
  saved batch threshold.
- **TraceCanary: `campaign run --save-summary` printed before refusing.** A
  colliding summary path used to leave a printed campaign report and exit 2;
  all destinations are now checked before the campaign runs.

- Both packages reject non-regular JSON inputs before reading them, so named
  pipes cannot indefinitely block local checks. Validation uses the opened
  descriptor, while ordinary files and symlinks to regular files remain supported.
- The Corridor Lab README documented the test suite without the
  `PYTHONPATH=src` setting that CI uses, so the documented command failed on
  a clean checkout. The README now shows the command that CI runs and that
  `CONTRIBUTING.md` documents.
- Corridor Lab desktop: after **Open Project...**, **Save Report...** and
  evidence export protected only the scenario file, so they could overwrite the
  project manifest, baseline, or variant files and leave a project that no
  longer validates. Reports now refuse any destination inside the open project
  directory, as `project run --output` already did.
- Corridor Lab `project add-variant` checked the new name only against derived
  variants, so reusing the name of a file variant saved with
  `project create --variant NAME=PATH` silently replaced that entry in the
  manifest. It now refuses any existing variant name with exit 2 and leaves the
  manifest unchanged.
- TraceCanary desktop: **Run Campaign** checked only the Input selector and
  ignored the Candidate selector, which **Open Project...** fills from a saved
  `--candidate`. A project with a passing baseline and a leaking candidate
  therefore passed in the desktop while `campaign run` reported the
  regression. The desktop campaign now checks both selections, as
  `campaign run` does, and protects the candidate from summary saves.
- TraceCanary `campaign compare` crashed with a Python traceback and exit 1,
  the regression status, when a saved summary had a wrongly typed part (for
  example a phase that is not an object, or a non-list `required_fields`), and
  the desktop **Compare Saved Summaries...** raised the same error. Such
  summaries are now unresolved (exit 2) with a message naming the malformed
  part, never a value.

## [0.3.0] - 2026-10-09

Both packages ship 0.3.0, tagged `corridor-lab-v0.3.0` and
`tracecanary-v0.3.0` on the same `main` commit. This section covers every
change on `main` since 0.2.0 (2837b4c). The real-window Windows acceptance in
`RELEASE-CHECKLIST.md` is a separate gate from these notes.

### Added

- Installed-wheel saved-project journeys for both packages, including moved
  projects, evidence safety, and modified-input refusal.
- Timed headless smoke checks of both built portable Windows executables.
  Real-window acceptance remains a separate release gate.
- **`--version` on every entry point.** `corridorlab`, `corridorlab-gui`,
  `tracecanary`, and `tracecanary-gui` print their name and version. The
  desktop window titles show the version too, because the Windows GUI
  launchers have no console. Each package's `__version__` is now the single
  source of truth: `pyproject.toml` reads it through
  `[tool.setuptools.dynamic]`, and the installed journeys check the
  distribution metadata and the installed `--version` output against it.
- **Versioned SARIF.** TraceCanary's SARIF `tool.driver` now carries
  `version` and `semanticVersion`, so code-scanning uploads name the release
  that produced them.

#### Corridor Lab

- **Saved local projects.** Portable `corridor-lab.project/v1` manifests
  bundle a scenario, route selection, baseline, named variants, and saved
  experiment configurations with relative paths and SHA-256 input
  fingerprints. Create, validate, open, and rerun from the CLI or the
  desktop; moving a self-contained project directory keeps it valid, and
  missing or modified inputs are reported instead of silently accepted.
  Reports cannot replace project inputs or land inside the project
  directory.
- **Scenario variants.** Derived variants apply controlled changes to
  declared transaction and route fields while preserving every other
  field, with an exact-decimal assumption diff before any result and a
  variant comparison across the declared set (currencies, units,
  guardrail satisfaction; declared cases, never a representative
  distribution, no composite score). `run-variants` reruns a saved
  experiment per variant.
- **Target and constraint analysis.** `target-search` evaluates declared
  candidate values against declared constraints per route (sender-cost
  ceiling, recipient floor, deadline probability, tail hours), reporting
  per-candidate rows, invalid candidates, the smallest tested feasible
  value per route (explicitly not an optimum), and unreachable tested
  sets. `robustness-review` checks constraints across supplied scenarios
  and names each route's first failing scenario.
- **Desktop workbench.** Four-tab workbench with structured
  exact-decimal transaction editing, saved projects, variants, targets,
  robustness, evidence export, and find-in-report. All desktop
  report/evidence exports carry the same input-collision protection as
  the CLI.

#### TraceCanary

- **Saved local projects.** Portable `tracecanary.project/v1` manifests
  hold the contract, synthetic inputs, baseline/candidate references,
  batch configuration, coverage thresholds, and population gates —
  fingerprinted and portable.
- **Regression campaigns.** One bounded pass over existing checkers and
  the batch engine with separate phase meanings (contract, control,
  baseline, candidates, batch, population gate). A failing baseline is
  never used; `project promote-baseline` promotes only validated
  passing candidates. Value-free deterministic summaries save
  explicitly; summary comparison enforces compatibility (same contract
  version) and aggregates findings by value-free code as persistent,
  resolved, or new.
- **Contract authoring and diagnosis.** `contract template` and
  `contract review` (conservative, actionable, value-free diagnostics:
  retention conflicts, malformed wildcard paths, paths stopping before
  a value, shadowed forbidden keys). The desktop gains a transactional
  contract editor whose save action is explicitly labeled as writing
  canary configuration.
- **Evidence exports.** Value-free evidence bundles (campaign summary,
  thresholds, tool version, limitations) that never bundle canary
  values, contracts, or trace inputs.
- **Canary collision diagnostic.** `contract review` reports a `conflict`
  at `canaries[N]` when a canary value occurs in TraceCanary's own fixed
  report wording (for example `PASS`), because every report containing that
  wording would be withheld with exit 2 and no output. The value is never
  echoed. The specification now lists every report mode the code emits,
  the `GUI007` and `GUI008` guidance codes, and how withheld reports behave.

#### Both packages

- CI now runs on Linux, Windows, and macOS for Python 3.11 through 3.14,
  and both packages declare Python 3.13 and 3.14 support. Both suites gave
  identical results on 3.13 and 3.14 before the classifiers were added.
- Dependabot keeps the SHA-pinned workflow actions current with one
  weekly grouped update. The portable Windows builds run on pull requests
  that change their workflow, launcher, or packaging, and never cancel a
  build already in progress.
- **Release gate.** `tools/check_release.py` enforces the lockstep version
  policy, the dynamic pyproject version, package `LICENSE` files equal to the
  root, and this file's structure (one Unreleased section, dated version
  sections in descending order, link references, no repeated subsections).
  It runs with its own unit tests in `Repo checks`. With `--tag` it gates both
  portable Windows workflows, which now trigger on `corridor-lab-v*` and
  `tracecanary-v*`, name their archives with the version, and also retain
  the wheel and sdist with a `SHA256SUMS` file. `--notes X.Y.Z` prints a
  section for release notes. This file now records 0.2.0, 0.1.1, and 0.1.0,
  which were set on `main` but never tagged, and both `docs/RELEASE.md`
  files describe the release process instead of one version.
- Measured bounded workloads are recorded in PROGRESS.md; results sit
  well inside all declared bounds.

### Changed

- **TraceCanary campaign population gates count each finding once and
  cover every input.** The population-gate phase copied every privacy
  finding that `population_gate` re-detects, so a gated campaign reported
  each canary leak and forbidden key twice in its totals and saved summary.
  It also gated only the first named candidate, never gated the batch, and
  showed a privacy regression as a population failure. The phase now holds
  one item per named candidate and only `TC013` findings, privacy findings
  stay in the candidates phase, and batch files are gated in the batch
  phase. `campaign_version` and `summary_version` are unchanged because the
  new fields are additive. Summaries saved before this release with a
  population gate carry the doubled counts, so comparing one with a newer
  summary reports those duplicates as resolved findings; rerun the older
  campaign before comparing. The desktop campaign now honours the
  **Recursive** and **Include paths** batch selectors, as `campaign run` and
  saved projects already did, and a population minimum that is not a whole
  number shows `GUI007` guidance instead of being dropped.
- **License metadata aligned to the repository's MIT license.** The root
  `LICENSE` is MIT, but both packages shipped an Apache-2.0 `LICENSE` and
  declared `License: Apache-2.0` in wheel metadata. Both package `LICENSE`
  files now carry the root MIT text, and each `pyproject.toml` declares the
  SPDX expression `license = "MIT"` with `license-files = ["LICENSE"]`. This
  replaces the TOML-table license and the license classifier, which setuptools
  deprecates and stops building after 2027-02-18. Wheels now carry
  `Metadata-Version: 2.4` and `License-Expression: MIT`.
- A new `Repo checks` workflow runs on every push and pull request, with no
  path filter, and lints the whole repository with pinned `ruff==0.16.10`
  (pyflakes and syntax errors, configured in the root `ruff.toml`). The
  dead imports and unused locals it found are gone; calls kept only for
  their validation keep the call and drop the name. `CONTRIBUTING.md` now
  lists the real local checks instead of `pnpm` commands and a type check
  that never existed.
- The root `SECURITY.md` is now the single security policy. It covers the
  case where GitHub private vulnerability reporting is not enabled (ask for a
  private contact in an issue with no technical detail) and supports the
  latest minor release of each package. The package policies keep their
  security boundaries and link to it instead of naming a `0.2.x` line or
  "the maintainers of the distribution". The issue templates gain the front
  matter GitHub's chooser needs, the bug template asks for `--version`
  output and synthetic inputs only, and a contact link points security
  reports at the policy. The Corridor Lab example README now says to run its
  commands from `packages/corridor-lab`, where the paths resolve.
- Corridor Lab `corridor-lab.evidence/v1` documents gain an additive
  `inputs.baseline` key (`null` when no baseline was read). Batch evidence
  describes `inputs.scenario` as each JSON scenario in the scanned directory.
- Wheel verification selects exactly one built distribution without a version
  literal; TraceCanary now verifies in an isolated environment.
- CI action pins use Node 24. Current-state and release documentation now
  points to this changelog and distinguishes verification from publication.

- Known platform limitation: full manual visual/interaction testing was
  performed on macOS arm64 only; Windows coverage includes an
  automated real-window background-batch regression in CI.

### Deprecated

- None.

### Removed

- **TraceCanary duplicated campaign-comparison renderer.** `cli.py` carried a
  byte-identical private copy of `campaign.render_comparison_human` under the
  name `render_campaign_human`, so `campaign compare --format human` did not
  use the function its own module documents as "shared by the CLI and the
  desktop". The copy is removed and the shared renderer is called directly.
  The internal `tracecanary.cli.render_campaign_human` name is gone; rendered
  output is byte-for-byte unchanged.

### Fixed

- **Corridor Lab `project run` and `project run-variants` crashed on Markdown.**
  Both commands advertise `--format markdown` (also chosen by a `.md`
  `--output` or `CORRIDOR_LAB_FORMAT=markdown`), but the Markdown renderer had
  no branch for `corridor-lab.project-run/v1` and fell through to the route
  table, so every such run ended in a `KeyError: 'routes'` traceback. Project
  runs now render a status table per experiment or variant followed by each
  passing item's own report, nested two heading levels down. A report kind the
  renderer does not know now fails with exit 2 and a diagnostic instead of a
  traceback.
- **Corridor Lab `compare-variants` called the expected recipient amount
  conditional.** The `metric_definition` for `expected_recipient_amount` read
  "conditional recipient amount", which `docs/MODEL.md` defines as the amount
  before weighting by success probability. It now reads "expected recipient
  amount (failure outcomes contribute zero)" in JSON, CSV, and Markdown. The
  metric values are unchanged.
- **Corridor Lab evidence documents misstated their inputs.** `batch
  --evidence` recorded the scenario as "built-in fictional demo",
  `robustness-review` recorded a Python list literal, and `diff` never named
  its baseline. In the desktop, evidence for a portfolio batch named whatever
  scenario had been loaded before it. Evidence now records the scanned batch
  directory, every reviewed scenario separated by `; `, and the diff baseline.
- **Corridor Lab wrote the report before refusing a colliding `--evidence`
  path.** `evaluate victim.json --output out.json --evidence victim.json`
  exited 2 but left `out.json` written. Both destinations are now checked
  against every input and each other before any analysis runs.
- **`CORRIDOR_LAB_FORMAT` broke project commands that emit no report.** An
  unsupported value such as `yaml` made `project validate` and `project
  create` exit 2. Project subcommands now resolve their own formats, as they
  already did for the commands that write reports.
- **TraceCanary refused to promote the candidate a project already held.**
  After `project create --candidate after.json`, the natural next step,
  `project promote-baseline PROJECT --candidate after.json`, failed with
  "project input already exists" because the project's copy has the same
  name. A byte-identical regular file already in the project is now reused;
  a different file with the same name, a link, or a folder is still refused.
  Promotion also validates the new manifest before writing it, so a
  manifest the loader would refuse never replaces a loadable one.
- **Source distributions could not run their own tests.** Both sdists
  shipped `test*.py` but not the data those tests read (examples, routes,
  fixtures, schemas, docs) or Corridor Lab's `tests/helpers.py`, which 22
  test modules import. The extracted suites failed with 22 and 43 problems.
  Each package now has a `MANIFEST.in` that grafts those directories, and
  CI builds each sdist outside the checkout, extracts it, and runs its suite
  on every operating system and Python version. Wheel contents are unchanged.
- **Corridor Lab variant changes could not name a route id that contains a dot.**
  ``route.ROUTE_ID.FIELD`` split on the first dot, so ``my.route`` was read
  as route id ``my`` and a field of ``route.fx_rate``. Route ids may contain
  dots. The field is now the longest known field suffix, and the rest is
  the route id.

- **Corridor Lab target search counted the candidate grid and not its summary rows.**
  A search of 512 data rows then appended one summary row per route and
  returned a report past the 512-row budget. The budget check now includes
  those summary rows.

- **Corridor Lab chain diffs listed a field a descendant had restored.**
  The assumption diff accumulated every write in the chain. A child that
  put the parent's deadline back to the scenario value still appeared as a
  change, with the base and variant numbers equal. Rows now keep only
  fields whose end value differs from the declared scenario.

- **Corridor Lab robustness review named every colliding scenario with the same id.**
  Derived variants keep the base ``scenario_id``, and the review ignored the
  caller label. A passing base and a failing variant were both reported as
  the base scenario, including the first failing case. When scenario ids
  collide, rows now use the label the caller supplied. Unique ids are
  unchanged.

- **TraceCanary accepted a newline as a canary value, then failed every report.**
  A canary value of a single newline is contained in every human and JSON
  rendering, so the protected-value check raised ``UnsafeReportError`` even
  when the trace was clean. Canary text, forbidden strings, and retained
  keys now reject newlines. A unit separator inside a longer sentinel is
  unchanged, so a path collision still fails closed without echoing it.

- **Corridor Lab accepted JSON lone surrogates that cannot be written as UTF-8.**
  ``json.loads`` turns ``\\uD800`` into a lone surrogate. ``validate`` then
  reported the scenario as valid, and a later report write failed while
  encoding UTF-8. Parsing now rejects unpaired surrogates in keys and
  strings, and still accepts a real supplementary-plane character.

- **Corridor Lab CSV formula guard ignored a leading control character.**
  A route label such as a NUL followed by ``=1+1`` was written as a raw cell.
  Spreadsheet software that skips the control then evaluates the rest as a
  formula. Leading C0 controls and DEL are now quoted the same way as ``=``.

- **TraceCanary file fingerprints trusted ``stat`` and then hashed the whole file.**
  A file that was larger than the byte budget, or that grew after ``stat``
  reported a short size, was hashed in full. The fingerprint now reads at
  most one byte past the budget and refuses the input when that read is longer.
- **TraceCanary contract editor accepted a duplicate-key draft and saved a file the loader refuses.**
  The editor parsed drafts with ``json.loads``, which keeps the last copy of a
  repeated key, then wrote the original text. Validation saw a legal contract
  and the saved file failed ``load_contract`` on the duplicate key. Draft
  checks now use the same duplicate-key rejection as the file loader, and the
  unloadable text is not written.
- **TraceCanary contract review said pass for a forbidden path that skipped an array index.**
  `spans`, `attributes`, and the other repeated OTLP fields are arrays, so the
  checker only ever sees an index in the next segment. A prefix such as
  `.../spans/attributes/...` never reaches a scalar, and review treated it as
  clean. Those prefixes are now malformed, the same way an empty segment is.
- **TraceCanary campaign population gate aborted the run when the first candidate could not be read.**
  Each candidate is already recorded as unresolved when its file is missing or
  invalid, and the rest of the campaign continues. The population gate then
  loaded `candidates[0]` again outside that handler, so a missing first file
  raised and the gate, the later candidates' population result, and any batch
  phase were never reported. The gate now records unresolved for that candidate
  and the campaign finishes.
- **TraceCanary recursive project batches ignored nested exports.** Saving
  `--batch-recursive` stored the flag, but the project copy and the SHA-256
  fingerprint only walked the top of the directory. Nested JSON was dropped on
  import, and a later edit to a nested file already inside the project left
  `project validate` green while `campaign run` read the changed file. The copy
  and the fingerprint now use the same nested, case-insensitive `.json` rule as
  `batch --recursive`. A batch with no subdirectories keeps its previous hash.
- **TraceCanary review accepted a trailing slash on a forbidden path.**
  Empty segments are rejected when they appear as `//`, but a single trailing
  slash was not. `pointer_matches` then compared that empty segment to a real
  key and the prefix never matched. A path that otherwise ended at
  `stringValue` contains the segment `value`, so the separate "stops before a
  scalar" warning did not fire either, and the review status was pass. A
  trailing slash is now the same empty-segment malformation as `//`.
- **TraceCanary contract review pointed at the wrong shadowed key.** Every other
  review location is a 1-based rule ordinal (`required_retained_fields[1]` is
  the first field, `forbidden_path_prefixes[1]` is the first prefix). Shadowed
  exact keys used `list.index`, which is 0-based, so the second key was
  reported as `forbidden_attribute_keys[1]` — the first key. The location now
  uses the same ordinal as the other rules.
- **Corridor Lab project updates could replace a readable manifest with one the loader rejects.**
  `project add-experiment` and `project add-variant` built a `ProjectManifest`
  and wrote it without the budget checks `parse_manifest` enforces on open.
  Past 64 experiments or 32 variants the command exited 0, then the next open
  raised and the previous manifest was already gone. `write_project` now parses
  the document it is about to write and leaves the existing file untouched when
  that parse fails.
- **Corridor Lab variant comparison dropped ancestor changes.** `variant_comparison`
  materialized each derived variant with `apply_variant`, which copies the
  project scenario and applies only that variant's own edits. A variant whose
  base is another variant therefore lost every ancestor change: the assumption
  diff and `run-variants` kept the chain, while compare reported metrics for a
  scenario that was never declared. Comparison now materializes the same chain,
  including when the report lists only the descendant.
- **Corridor Lab's worked sensitivity CSV could drift into fiction.** The
  example README documents three commands and the repository checks in the
  expected output of two of them: `expected/compare.md` is asserted against the
  renderer by `test_worked_markdown_fixture_matches_renderer`, while
  `expected/sensitivity.csv` was read by nothing. Any change to the sensitivity
  model or the CSV renderer, or any hand edit of the fixture, left the file
  describing numbers the tool no longer produces and the suite green. A test now
  regenerates the CSV from the documented command and compares it byte for byte.
  The fixture is unchanged.
- **TraceCanary batch file selection depended on the platform's filesystem.**
  `_iter_batch_files` delegated to `Path.glob("*.json")`, which pathlib compiles
  case-insensitively on Windows and case-sensitively on POSIX, so the same
  declared batch directory produced a different batch on each platform. It also
  disagreed with `project.fingerprint_tree`, which already used an explicit
  case-insensitive suffix test: a saved project's batch directory could contain
  a `.JSON` export that `project validate` fingerprinted but `batch --input-dir`
  ignored. Selection now uses the same explicit suffix rule as the fingerprint,
  and the rule is documented in the README. On Windows no result changes; on
  POSIX a capitalised `.JSON` export is now included, which is what a Windows run
  of the same directory already reported.
- **TraceCanary campaign evidence documents reported a copied tool version.**
  `TraceCanaryController.save_campaign_evidence` wrote
  `{"name": "tracecanary", "version": "0.2.0"}` as a literal in the controller,
  separate from `tracecanary.__version__` and from the `pyproject.toml` project
  version, and `test_evidence.py` asserted only `evidence_version`, so every
  `tracecanary.evidence/v1` document kept claiming the previous version after a
  release bump. Meanwhile `test_metadata.py` compared the declared project
  version against its own `"0.2.0"` literal, so the one bump that could have
  revealed the drift failed a test that is about GUI entry points and URLs
  instead. The controller now reads the package version, the evidence test
  asserts it, and the metadata test compares `tracecanary.__version__` with the
  declared project version so a legitimate bump needs no test edit. Output is
  unchanged at the current version.
- **Corridor Lab evidence documents reported a copied tool version.** The
  `tool.version` field in every `corridor-lab.evidence/v1` document came from a
  module-level `TOOL_VERSION = "0.2.0"` literal in `evidence.py`, separate from
  `corridor_lab.__version__` and from the `pyproject.toml` project version, and
  nothing compared them. A release bump therefore left every evidence document
  claiming the previous version with no test failing, in a document whose stated
  purpose is to let another operator know what was tested. `evidence.py` now
  reads the package version, and a test holds `__version__`, the declared
  project version, and the emitted document in agreement. Output is unchanged at
  the current version.
- **TraceCanary project batch fingerprinting ignored the caller's budget and
  hashed the batch directory twice.** `build_manifest` called
  `make_input_ref(folder=True)` with the module default of 256 files while a
  separate second `fingerprint_tree` call used the caller's `max_batch_files`,
  so a looser caller budget was silently refused at the 256-file default
  before the honoured call ever ran, and every byte in the batch directory was
  read and hashed twice. The one `make_input_ref` result now supplies both
  `path` and `sha256` and receives the caller's budgets, and the per-file
  `max_bytes` is threaded through to every input ref rather than only the
  batch. No CLI behaviour changes: the CLI never passed these arguments.
- **TraceCanary gated batch items reported a stale finding summary.**
  `batch --population-scope ... --population-minimum ...` merged the gate's
  TC013 violation into each item but kept the pre-merge `summary` object, so
  `summary.total` under-counted the findings actually listed. A leaking
  export that failed the gate reported `total: 2` against three listed
  violations, and the human renderer printed "2 finding(s)" above three
  lines. The summary is now recomputed from the merged violations. The
  counting itself moved out of `build_report` into a shared `summarize`
  helper rather than being written twice.
- **Corridor Lab CSV export mangled negative metric values.** The
  spreadsheet-formula guard prefixed any cell starting with `=`, `+`, `-`,
  `@`, tab, or CR, so declared negative metrics were written as text with a
  leading apostrophe: a `-0.04` probability delta became `'-0.04`, a `-6`
  guardrail headroom became `'-6`. Every CSV column that can legitimately go
  negative (scenario-diff `delta`, guardrail headroom, break-even cost
  deltas) was affected. A cell that is exactly a plain decimal number is now
  left alone; a sign followed by anything else is still prefixed, so the
  injection guard is unchanged for text.
- **TraceCanary campaign summaries could replace a campaign input.**
  `campaign run --save-summary PATH` only protected the project contract,
  so pointing it at a `--candidate`, `--control`, or `--baseline` file
  outside the project directory overwrote that export with the value-free
  summary. Every input the run actually read is now protected, matching the
  contract itself. Regression covers the collision.
- **TraceCanary `contract review` could destroy its own input.**
  `contract review CONTRACT --output CONTRACT` wrote the review report over
  the contract file and still exited 0, silently losing the reviewed
  contract. The output path is now checked against the contract, matching the
  protection every other report-writing command already applied. A
  regression test covers the collision and the still-valid separate path.
- **TraceCanary saved coverage thresholds.** `campaign run PROJECT` now
  applies the saved `coverage.minimum_ratio` to named candidates instead of
  silently omitting the gate unless the CLI option is repeated. Explicit
  overrides, including zero, take precedence without changing the project;
  summaries record the effective threshold and reject incompatible comparisons.
  The separately saved batch threshold remains independent.
- **TraceCanary saved-candidate campaigns.** `campaign run PROJECT` now
  evaluates the candidate saved by `project create --candidate`, alongside
  the saved input and any explicitly added candidate. Previously a saved
  leaking or malformed candidate could be omitted, yielding a passing
  campaign and a summary with zero candidates. Regression tests cover
  pass/regression/unresolved outcomes, baseline safeguards, fingerprint
  rejection, value-free summaries, and summary comparisons.
- **Corridor Lab (Milestone 8).** Materializing a variant mutated the
  caller's declared base data, so later assumption diffs lied;
  materialization is now deep-copied and a regression proves the base is
  never mutated.
- **TraceCanary (Milestone 8).** `promote-baseline` was calling the
  fingerprint helper with the wrong signature; regression added.

### Security

- **TraceCanary printed texts the protected-value check never saw.** Every
  report is meant to be withheld, silently and with exit 2, when a protected
  canary value occurs in its text. `contract review` (CLI and desktop) checked
  only the review object, then printed a human rendering whose fixed wording
  could contain the value: a contract whose canary was `TraceCanary` reviewed
  as `TraceCanary contract review: PASS`. The desktop campaign returned its
  human rendering unchecked as well. `campaign run` and the contract commands
  caught the withheld-report error as an ordinary failure and printed
  `TraceCanary: UNRESOLVED: `, which itself contains values such as `race`.
  Review and campaign texts, and a campaign summary before it is saved, are
  now checked as emitted, and every withheld result is silent.

### Compatibility

- Python 3.11+; standard-library runtime; offline; no new entry points
  removed; all existing command names, report contracts, deterministic
  outputs, and status semantics preserved.

## [0.2.0] - 2026-09-10

Both packages were set to 0.2.0 on `main` in 2837b4c. This version was never
tagged or published as a release; the summaries below are moved verbatim from
the two `docs/RELEASE.md` files.

### Added

#### Corridor Lab

- Version 0.2.0 adds signed guardrail headroom, a weighted outcome ledger,
  deadline/resolution profiles, whole-volume break-even checks, and bounded
  transaction grids. Existing route evaluation and ranking semantics remain
  unchanged.

#### TraceCanary

- Version 0.2.0 adds value-free contract inspection, exact coverage gates and
  comparisons, missing-retention matrices, and weighted batch coverage.
  Existing check and diff semantics remain unchanged. A release build must run
  from a clean checkout on Windows and Ubuntu with Python 3.11 or newer.

## [0.1.1] - 2026-08-03

Corridor Lab was set to 0.1.1 in 8f00cde and TraceCanary in d7fbaaf, while
each package still had its own history. This version was never tagged or
published as a release; the summaries below are the `docs/RELEASE.md` text
that 2837b4c replaced.

### Added

#### Corridor Lab

- Version 0.1.1 pins the setuptools build backend and adds bounded batch
  portfolios, explicit two-parameter stress grids, and a Pareto frontier that
  keeps expected recipient amount and expected sender cost separate.

#### TraceCanary

- The package version, pinned setuptools build backend, and deterministic
  batch report formats are the v0.1.1 release boundary. A release build must
  run from a clean checkout on Windows and Ubuntu with Python 3.11 or newer.

## [0.1.0] - 2026-08-02

Initial releases: Corridor Lab in 550a70d and TraceCanary in be75fb9, each the
root commit of its own history. On 2026-08-30, 4864a4f established this
repository's package layout and 422a9c9 imported the TraceCanary history into
it. This version was never tagged.

### Added

- Corridor Lab 0.1.0, the first deterministic comparison of fictional
  cross-border payment routes.
- TraceCanary 0.1.0, the first synthetic-canary privacy-regression checker
  for OTLP/HTTP JSON trace exports.

## Milestone history

This section preserves the milestone-by-milestone development record
previously maintained in `PROGRESS.md`. The program branch was
`dev/program-cycle-1` (from `main` at `45776ea`, the PR #30 merge).

### Baseline (PR #30 merged)

- Desktop workbenches with tabbed workflows, protected atomic report
  exports with tracked-input collision guards, exact-decimal structured
  transaction editing, controller/CLI report agreement, shared bounded
  batch engine with background execution and main-thread-only widget
  updates, synthetic starter bundles covering every acceptance case.
  Verified merged via PR #30.
- Baseline verification: corridor-lab 141 tests, tracecanary 151 tests,
  compile checks, both GUI smoke tests from the checkout and from clean
  installed packages with `PYTHONPATH` unset.

### Milestone 1: reusable local projects (complete pending PR)

Design decisions (lasting rationale):

- Each package gets its own project manifest format; no shared runtime:
  `corridor-lab.project/v1` and `tracecanary.project/v1`. Manifests are
  strict canonical JSON with explicit bounds and duplicate-key
  rejection, like every other package input.
- Relative paths resolve against the project directory; moving a
  self-contained directory keeps it valid. Absolute paths are refused so
  a project stays portable.
- Every referenced input stores a SHA-256 content fingerprint at save
  time; opening reports missing or modified inputs instead of silently
  accepting them. Fingerprints detect change, they never claim identity
  of entities.
- Result evidence stays out of the manifest. Reopening a project must
  not imply an old report describes current inputs; reports carry their
  own declared inputs and the GUI clears stale results on reopen.
- Saving is explicit: create/save-as write to a user-chosen location and
  refuse to replace an existing manifest silently.
- The same source chosen twice (input == baseline) is stored once and
  referenced twice; distinct sources with colliding names are refused.

Implemented (corridor-lab): `projects.py` library, CLI
`project create|validate|open|add-experiment|run` (combined
deterministic project-run reports; reports protected against replacing
inputs or landing inside the project), controller open/save/run, GUI
Open Project / Save Project As / saved-experiment section with a
transactional save-current-settings dialog. Acceptance flow verified
from the installed package: create -> close -> move -> reopen ->
identical deterministic rerun; modified inputs refuse to run with clear
diagnostics.

Implemented (tracecanary): `project.py` library (contract, input,
baseline, candidate, batch directory with tree fingerprints, coverage
threshold, population gate), CLI `project create|validate|open`,
controller open/save, GUI Open Project / Save Project As on the Files
tab. Acceptance flow verified from the installed package including
value-free human summaries.

Corridor tests: 157. TraceCanary tests: 164. Both suites, compile
checks, and GUI smoke tests green at commit `2569645`.

### Milestone 2: Corridor Lab scenario experimentation (implemented on `dev/scenario-experimentation`, base: `dev/program-cycle-1`)

- `variants.py`: derived variants with strict change validation
  (transaction fields plus declared route fee/spread/liquidity fields),
  materialization that preserves every unchanged field, exact-decimal
  assumption diffs, and a variant-comparison analysis table with
  currencies, units, guardrail satisfaction, and an explicit
  not-a-distribution note. No composite score.
- Manifest variants section accepts file references (existing) or
  derived specs (`base: "scenario"` only; chained bases deferred).
- CLI: `project add-variant | show-variant | compare-variants |
  run-variants` with the same input protection as other project
  commands.
- Desktop: variants section on the Investigate tab (Show Assumption
  Diff, Apply Variant, Compare Variants); applied variants are
  in-memory, unsaved, and clearly labeled; controller/CLI agreement
  asserted.
- Corridor tests: 171. Real-window drive passed on macOS arm64.

### Milestone 3: target and constraint analysis (implemented)

- `targeting.py`: strict constraint grammar (four kinds, op enforced per
  kind, currencies attached to cost/amount units), `target_search` over
  declared candidate sets with invalid-candidate reporting, per-route
  summaries ("smallest tested feasible value" — explicitly not an
  optimum — and `unreachable_within_tested_set`), row budget preserved;
  and `robustness_review` across supplied scenarios with matching
  currencies and first-failing-scenario per route. Declared cases,
  never forecasts.
- CLI: `target-search` and `robustness-review` (multiple scenario
  files; report-input protection extended to multi-file commands).
- Desktop: Target Search and Robustness Across Project Scenarios in
  the Investigate tab; the robustness case set is the base scenario
  plus derived variants.
- Hand-derived expected-cost check (fixed + percent + carry/volume +
  loss) and boundary tests: corridor-lab at 182 tests. Real-window
  drive passed.

### Milestone 4: TraceCanary regression campaigns (implemented)

- `campaign.py`: one bounded pass over existing checkers and the batch
  engine. Phases with separate meanings (contract, control, baseline,
  candidates, batch, population gate); a failing baseline is never
  used; unresolved precedence preserved; the combined document is
  re-checked against canary values. Value-free deterministic summaries
  save only through explicit actions; `compare_summaries` performs
  strict compatibility checks (same contract version, summary version)
  and aggregates findings by value-free code as
  persistent/resolved/new with no entity identity implied.
- CLI: `campaign run [--save-summary]`, `campaign compare`, and
  `project promote-baseline` (explicit, validated promotion only).
- Desktop: new **Regression Campaign** tab (7) with background
  execution, main-thread-only widget updates, a new Control
  (unsanitized) selector, Save Summary As..., and Compare Saved
  Summaries.
- TraceCanary tests: 174. Real-window drive passed on macOS arm64.

### Milestone 5: contract development and diagnosis (implemented)

- `authoring.py`: the runtime validator stays authoritative; the
  review covers only what it cannot — retention conflicts with
  actionable rule locations, malformed wildcard paths, paths stopping
  before a scalar value, and forbidden keys shadowed by prefixes.
  Value-free (canary values never appear); passing review is not a
  privacy guarantee.
- CLI: `contract review`, `contract template` (never overwrites).
- Desktop: **Review Contract** and **Edit Contract JSON...** —
  transactional editor (template / load selected / validate / Save
  Contract As...) whose export is explicitly labeled as containing
  canary configuration, distinct from value-free report exports.
- TraceCanary tests: 183. Real-window drive passed on macOS arm64.

### Milestone 6: evidence exports and find-in-report (implemented)

- Corridor Lab `evidence.py`: Export Evidence bundles the current
  report verbatim with tool version, analysis identity, declared input
  sources, and standing limitations; atomic, size-bounded,
  input-collision protected.
- TraceCanary: Save Evidence bundles the value-free campaign summary,
  thresholds, tool version, limitations. The summary is rebuilt from
  known fields, the protected-value check runs before any write, and
  contracts/canaries/inputs are never bundled (hashes of protected
  values are not treated as anonymization).
- Both desktops gained find-in-report highlighting.
- Charts deliberately deferred (documented in ROADMAP): text-first
  tables keep exact values; no chart library is allowed beyond the
  standard library, and an ASCII approximation would obscure rather
  than clarify.
- Corridor 182 tests, TraceCanary 186 tests.

### Milestone 7: cross-platform reliability and performance (implemented)

- CI: macOS added to both package test matrices
  (ubuntu/windows/macos x 3.11/3.12). Portable Windows build workflows
  unchanged.
- New display-guarded window tests: batch results applied on the main
  thread, window closure during work leaves no crash or stale callback,
  repeated batch runs re-enable and re-run.
- Measured bounded workloads (macOS arm64, Python 3.11.16; observation
  only, scripts in each package's tests/measure_workloads.py): corridor
  transaction sweep (24 values x 6 routes) 0.0065 s, stress grid
  (2x24 cells x 6 routes) 0.0097 s, JSON render/parse ~0.4 ms each;
  tracecanary batch (32 files x ~120 KB) 0.0625 s. Well inside all
  bounds; no optimization required and none of the limits changed.

### Milestone 8: integrated journeys and release readiness (implemented)

- Corridor journey (installed package, `PYTHONPATH` unset): create
  project → stage and apply variants → truthful assumption diffs → run
  saved experiment → compare across variants → target search
  (smallest tested feasible value) → robustness across variants →
  export evidence → save-as → reopen in a fresh controller → rerun.
- TraceCanary journey (installed): contract template → review
  (actionable diagnostics) → project with thresholds → control check
  (labeled not a privacy pass) → leak detection → campaign →
  coverage gate → value-free summaries → comparison → value-free
  evidence → move → reopen → explicit validated baseline promotion.
- RELEASE-NOTES.md and RELEASE-CHECKLIST.md drafted (owner approval
  required for any release); root README gains a documentation map.
- Final suites: corridor 183 tests, tracecanary 189 tests, compile
  checks, GUI smoke tests — green at the final head.

### Program state (checkpoint, as preserved from PROGRESS.md)

- Branch `dev/scenario-experimentation`, head `828fbb4`; both workflows
  green (Linux/Windows/macOS x 3.11/3.12).
- PRs awaiting owner approval: #31 (M1, base main) and #32 (M2-M8
  commits, base dev/program-cycle-1). The developer never merges own
  work.
- All eight milestones implemented; integrated journeys verified from
  installed packages; release material prepared but nothing merged,
  tagged, or published.
- Resumption note: branch `dev/scenario-experimentation` at `93ad0cc`,
  CI green on both workflows, PRs #31 (M1, base main) and #32 (M2,
  base dev/program-cycle-1) open awaiting owner approval; M3-M5
  commits are stacked on the same branch and will appear in PR #32 or
  follow-ups.
- Await owner approval/merge of PRs #31/#32, then execute
  RELEASE-CHECKLIST.md.

### Verification commands (authoritative, from PROGRESS.md)

```text
cd packages/corridor-lab && PYTHONPATH=src python -m unittest discover -s tests -v && python -m compileall -q src
cd packages/tracecanary && python -m unittest discover -s tests -v && python -m compileall -q src
corridorlab-gui --smoke-test && tracecanary-gui --smoke-test   # after installation
```

### Blockers

None.

## Notes on this consolidation

- The `[Unreleased]` section above is the consolidated release draft
  (sourced from `RELEASE-NOTES.md`).
- The `Milestone history` section above is the consolidated development
  status (sourced from `PROGRESS.md`).
- Both source files now carry a single-line deprecation note at the top
  pointing readers to this CHANGELOG.md.
- No content has been invented; every entry traces back to
  `RELEASE-NOTES.md` or `PROGRESS.md`.

[Unreleased]: https://github.com/EauDoon/operator-labs/compare/corridor-lab-v0.3.0...HEAD
[0.3.0]: https://github.com/EauDoon/operator-labs/compare/2837b4c...corridor-lab-v0.3.0
[0.2.0]: https://github.com/EauDoon/operator-labs/compare/8f00cde...2837b4c
[0.1.1]: https://github.com/EauDoon/operator-labs/compare/550a70d...8f00cde
[0.1.0]: https://github.com/EauDoon/operator-labs/commit/550a70d
