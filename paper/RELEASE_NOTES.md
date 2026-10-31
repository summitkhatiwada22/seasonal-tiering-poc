**Forecasting versus Reactive Cloud Auto-Tiering: A Pre-Registered, Fee-Accurate Test**, by Summit Khatiwada (version 1.0, October 2026).

**Result:** by rules fixed and tagged before the sealed years were opened (`freeze-g3`), forecasting does not beat S3 Intelligent-Tiering.

- A per-file choice of storage policy was 39% to 54% cheaper on Wikipedia and npm in 2024–2025 when up to 1% of reads may wait.
- It failed because in 2024 slightly more of its reads waited than the rival's (0.277% vs 0.245%; 0.118% vs 0.089%).
- It lost on library data, and with no waiting allowed nothing beat managed tiering.
- A reference that knew each file's true read rate passed every Wikipedia and npm line.

**Contents**
- `forecasting-vs-reactive-auto-tiering.pdf`: the paper (14 pages, 7 figures).
- Every number: `docs/RESULTS.md`.
- Rules written first: `docs/PREREGISTRATION.md`.
- Decision log: `docs/DECISIONS.md`.
- Reproduce: `git checkout freeze-g3`, then the commands in the README.

**Licences:** code is MIT; the paper and documentation are CC BY 4.0.

**AI use:** done with the help of Claude (Anthropic) under the author's direction; see the paper's "Use of AI" section.

