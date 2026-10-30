"""Command line for early check E1 (see docs/E1_PROTOCOL.md).

python -m sat.experiments run --period tune --setting central [--datasets D1 D3] [--workers 2]
python -m sat.experiments pick --setting central
python -m sat.experiments run --period eval --setting central
python -m sat.experiments verdict --setting central
"""

from __future__ import annotations

import argparse
import json

from sat.experiments.e1 import REAL, SETTINGS, SYNTH, run
from sat.experiments.select import verdict, write_picks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sat.experiments")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--period", choices=["tune", "eval"], required=True)
    r.add_argument("--setting", choices=list(SETTINGS), required=True)
    r.add_argument("--datasets", nargs="+", default=[*REAL, *SYNTH])
    r.add_argument("--workers", type=int, default=2)
    p = sub.add_parser("pick")
    p.add_argument("--setting", choices=list(SETTINGS), required=True)
    v = sub.add_parser("verdict")
    v.add_argument("--setting", choices=list(SETTINGS), required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args.period, args.setting, args.datasets, args.workers)
    elif args.command == "pick":
        print("wrote", write_picks(args.setting))
    else:
        out = verdict(args.setting)
        print(json.dumps({k: v for k, v in out.items() if k != "lines"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
