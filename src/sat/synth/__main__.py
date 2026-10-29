"""Command line: ``python -m sat.synth --scale S --out data/processed/synthetic_S``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from sat.synth.generator import SynthConfig, generate

MAX_IN_MEMORY_OBJECTS = 200_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sat.synth", description="Generate synthetic access logs (dataset D7)."
    )
    parser.add_argument("--scale", choices=["S", "M", "L"], default="S")
    parser.add_argument("--config", type=Path, default=Path("configs/datasets/synthetic.yaml"))
    parser.add_argument("--objects", type=int, help="override the object count of the scale")
    parser.add_argument("--days", type=int, help="override the number of days")
    parser.add_argument("--seed", type=int, help="override the random seed")
    parser.add_argument(
        "--no-seasonality", action="store_true", help="build the control: peaks flattened"
    )
    parser.add_argument("--out", type=Path, required=True, help="output folder")
    args = parser.parse_args(argv)

    settings: dict[str, Any] = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    n_objects = args.objects or int(settings["scales"][args.scale]["objects"])
    if n_objects > MAX_IN_MEMORY_OBJECTS:
        parser.error(
            f"{n_objects:,} objects is too many to build in memory "
            f"(limit {MAX_IN_MEMORY_OBJECTS:,}); the streaming writer arrives in Phase 2"
        )

    cfg = SynthConfig(
        n_objects=n_objects,
        start=settings["start"],
        n_days=args.days or int(settings["days"]),
        seed=args.seed if args.seed is not None else int(settings["seed"]),
        seasonality=not args.no_seasonality,
    )
    data = generate(cfg)

    args.out.mkdir(parents=True, exist_ok=True)
    data.objects.write_parquet(args.out / "objects.parquet")
    data.reads.write_parquet(args.out / "reads.parquet")
    summary = {
        "objects": data.objects.height,
        "read_rows": data.reads.height,
        "total_reads": int(data.reads["reads"].sum()),
        "seasonality": cfg.seasonality,
        "seed": cfg.seed,
        "start": cfg.start.isoformat(),
        "days": cfg.n_days,
    }
    (args.out / "run.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
