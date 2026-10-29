# Decision log

One entry per choice that could change results. Newest at the bottom. Never edit an old entry; add a new one that supersedes it.

| ID | Date | Decision | Why | Alternatives rejected |
| --- | --- | --- | --- | --- |
| D-001 | 2026-10-29 | Python 3.12 or newer, managed with uv and a lockfile | A clean machine (Codespace, CI, laptop) installs the identical environment | pip with loose requirements: results could drift between machines |
| D-002 | 2026-10-29 | Garage or SeaweedFS for the local object store (Phase 9) | MinIO's open-source repository was archived in April 2026 | MinIO |
| D-003 | 2026-10-29 | Re-ordered the plan: early check E1 after Phase 4; seasonal-naive policy built in Phase 4; compression and live demo only after Gate G3; customer conversations start now; 6-week cap | Fail fast and cheaply; do not build demos for a result that has not passed | Original order (11 phases, no early stop) |
| D-004 | 2026-10-29 | Price sheets compiled from secondary articles; every value flagged `sourced` or `unverified`; official pricing pages checked in Phase 1 | Provider pages could not be fetched here; honesty about provenance is better than silent guesses | Writing numbers with no provenance |
| D-005 | 2026-10-29 | Repository stays private; licence chosen after the PoC result | Public code before a decision weakens your position | Public from day one |
| D-006 | 2026-10-29 | Synthetic generator uses the real calendar (leap years) and one random stream per block of 5,000 objects | Reproducible output, bounded memory, and a block can be regenerated alone | One global stream (output would depend on run order) |
| D-007 | 2026-10-29 | Synthetic control (`seasonality=False`) keeps the same objects and expected volume, flattening each yearly peak | Gives a true "no seasonality" test: any gain measured on it is a false win | Generating an unrelated dataset |
| D-008 | 2026-10-29 | Model single-region storage prices only (GCS us-central1, AWS us-east-1, Azure East US) | Matches the official pages we could read; multi-region prices differ and changed in 2026 | Mixing single- and multi-region |
| D-009 | 2026-10-29 | Where a dataset has no object sizes (D1, D3, D4), draw sizes from a distribution calibrated on D5 and report results at low, central and high size settings | Sizes drive archive overhead and minimum-size charges, so a silent guess could create or hide a saving | One fixed size for everything |
| D-010 | 2026-10-29 | Keep our own copy and SHA-256 of any source that is updated in place (D4) and state resolution limits (monthly) with every D4 result | The publisher may revise old values; a re-download must never change a reported number | Re-fetching at report time |
| D-011 | 2026-10-29 | Run all data downloads from a Codespace or the owner's computer, not the build workspace | Every data server was blocked from the workspace on 2026-10-29 | Skipping real data |
| D-012 | 2026-10-29 | Repository is public for now (supersedes D-005) | Owner decision: Claude could not reach the private repository from this session. Nothing sensitive is committed; unreleased findings and outreach notes stay out of the repository | Private repository |
| D-013 | 2026-10-29 | Azure sheet is East US 2, LRS, flat namespace (refines D-008) | The owner's screenshots show those selectors; prices were read from them | East US (never shown in any source) |
