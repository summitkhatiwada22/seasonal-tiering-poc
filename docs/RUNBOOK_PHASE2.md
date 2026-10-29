# Phase 2 runbook (run in your own Terminal, not in the build workspace)

Set once per Terminal window:

    cd ~/Projects/seasonal-tiering-poc && git pull
    export SAT_CONTACT=summitkhatiwada22@gmail.com
    export WIKIMEDIA_CONTACT=$SAT_CONTACT
    D=~/Projects/seasonal-tiering-data

Every download command can be stopped with Ctrl-C and run again; it continues where it stopped.

## Step 0: small trial runs (minutes; do these first)

    uv run python -m sat.ingest.d4_seattle inspect --data-dir $D --years 2016
    uv run python -m sat.ingest.d4_seattle fetch --data-dir $D --years 2016 --max-pages 1
    uv run python -m sat.ingest.d3_npm list --data-dir $D --packages 5 --head 2
    rm $D/interim/D3/packages.csv   # the 5-package trial list must not become the real list

Send me the printed output of each command.

## Step 1: Wikipedia (D1)

    uv run python -m sat.ingest.d1_wikipedia list --data-dir $D --articles 5000
    uv run python -m sat.ingest.d1_wikipedia fetch --data-dir $D --workers 4
    uv run python -m sat.ingest.d1_wikipedia flags --data-dir $D
    uv run python -m sat.ingest.d1_wikipedia build --data-dir $D

(Delete the old pilot files first: `rm -r $D/raw/D1/views.jsonl* $D/interim/D1 $D/processed/D1`.
The cached monthly lists in `raw/D1/top` can stay.)

## Step 2: Seattle (D4), npm (D3), sizes (D2, D5)

    uv run python -m sat.ingest.d4_seattle fetch --data-dir $D
    uv run python -m sat.ingest.d4_seattle build --data-dir $D
    uv run python -m sat.ingest.d3_npm list --data-dir $D --packages 300
    uv run python -m sat.ingest.d3_npm fetch --data-dir $D
    uv run python -m sat.ingest.d3_npm flags --data-dir $D
    uv run python -m sat.ingest.d3_npm build --data-dir $D
    uv run python -m sat.ingest.calibration d2 --data-dir $D

D5: in a browser, open https://iotta.snia.org/traces/key-value/36305, accept the licence and
download the smallest trace (about 4 MB) into `$D/raw/D5/`. Then:

    uv run python -m sat.ingest.calibration d5 --data-dir $D --file $D/raw/D5/<filename>

## Step 3: quality report

    uv run python -m sat.ingest.quality --data-dir $D --out $D/reports
