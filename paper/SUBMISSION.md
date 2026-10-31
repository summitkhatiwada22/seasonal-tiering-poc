# Submitting and archiving the paper

Ready-made text for the places this paper goes. Every number here is from `docs/RESULTS.md`.

## Metadata

- **Title:** Forecasting versus Reactive Cloud Auto-Tiering: A Pre-Registered, Fee-Accurate Test
- **Author:** Summit Khatiwada (Independent Researcher, Kathmandu, Nepal)
- **Licence:** CC BY 4.0 (paper); MIT (code)
- **arXiv categories:** primary cs.DC (Distributed, Parallel, and Cluster Computing); cross-list cs.PF (Performance)
- **Comments field:** 14 pages, 7 figures. Pre-registered; code, protocols and all results at https://github.com/summitkhatiwada22/seasonal-tiering-poc
- **Keywords:** cloud storage, storage tiering, S3 Intelligent-Tiering, archival storage, demand forecasting, pre-registration, negative result

## Short abstract (under arXiv's 1,920-character limit)

Cloud archives tier data reactively: S3 Intelligent-Tiering, Google Autoclass and Azure smart tier move a file down after it goes unread and back when it is read. We tested whether forecasting when files will be read does better. A fee-accurate simulator, validated against hand calculations, the AWS Pricing Calculator and 48 planted bugs, billed 161 AWS policies per file per day on public demand data (Wikipedia page views, npm downloads, Seattle library checkouts) mapped to archive reads. Methods were fixed before scoring: an early check on 2023, two rolling years, and a sealed test on 2024-2025 that was pre-registered and run once from a frozen git tag. Seasonal forecasting alone never beat Intelligent-Tiering. A per-file choice of policy was 39-54% cheaper on Wikipedia and npm in the sealed years when up to 1% of reads may wait, by leaving a few large, rarely read files in deep archive behind restores of up to 48 hours. It still failed the pre-registered test: in 2024 slightly more of its reads waited than the rival's (0.277% vs 0.245%; 0.118% vs 0.089%). It lost on library data, and with no waiting allowed nothing beat managed tiering. A reference that knew each file's true read rate passed every Wikipedia and npm line: the per-file economics hold, but predicting next year's reads from last year's does not.

## arXiv source package

`make -C paper arxiv` builds `paper/arxiv-source.tar.gz` (main.tex, the .bbl, the preamble and the figures). Upload that file, not the PDF: arXiv rebuilds TeX papers from source.

## Order of steps

1. Zenodo: sign in with GitHub at https://zenodo.org, open the GitHub settings page, and switch this repository on.
2. GitHub release: create release `paper-v1.0` on `main`, paste `RELEASE_NOTES.md`, attach `forecasting-vs-reactive-auto-tiering.pdf`. Zenodo archives it and issues a DOI.
3. Add the DOI to `CITATION.cff` and the README (badge from Zenodo).
4. arXiv: submit the source package with the metadata above. A first-time submitter needs an endorsement from an established author in cs.DC.
