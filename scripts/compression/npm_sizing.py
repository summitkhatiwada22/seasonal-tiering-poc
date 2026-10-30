"""Compression sizing test on real npm tarballs (round two, stage 5b, decision D-047).

Downloads the latest version and up to five earlier versions of each D3 package (the list in
data_records/D3/packages.csv) from registry.npmjs.org, stopping at about 100 MB of tarballs, into
a scratch folder outside the repository, measures them, and deletes them. Only measurements are
kept (reports/compression/npm_sizing.json and npm_sizing_packages.csv).

What is measured (every codec round-trips byte for byte, checked by SHA-256):
  1. per tarball: the published .tgz (gzip) against the same tar recompressed with gzip -9,
     zstd -3, zstd -19 and xz -9 (LZMA2 preset 9);
  2. per package: all its downloaded versions in one solid stream (zstd -19 long window, xz -9)
     against the sum of its published .tgz files: what keeping versions together gains;
  3. whole-file deduplication: the share of file bytes inside the tarballs that repeat an earlier
     file (same SHA-256), across versions and packages;
  4. a zstd dictionary (110 KB) trained on the latest tarballs of half the packages, used on the
     latest tarballs of the other half, against zstd -19 without it;
  5. speed of each codec on the whole corpus (single thread, this workspace's CPU).

Run: uv run --with zstandard==0.25.0 python scripts/compression/npm_sizing.py
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import lzma
import platform
import shutil
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

import zstandard as zstd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "reports" / "compression"
PACKAGES = REPO / "data_records" / "D3" / "packages.csv"
CAP_BYTES = 100 * 2**20
VERSIONS = 6
UA = "seasonal-tiering-poc compression sizing (github.com/summitkhatiwada22/seasonal-tiering-poc)"


def get(url: str, accept: str | None = None) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, **({"Accept": accept} if accept else {})}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def versions(pkg: str) -> list[tuple[str, str]]:
    """The last VERSIONS versions in publication order (the abbreviated registry document lists
    versions in the order they were published), skipping pre-releases."""
    doc = json.loads(
        get(
            f"https://registry.npmjs.org/{pkg.replace('/', '%2F')}",
            accept="application/vnd.npm.install-v1+json",
        )
    )
    vers = [v for v in doc.get("versions", {}) if "-" not in v]
    picked = vers[-VERSIONS:]
    return [(v, doc["versions"][v]["dist"]["tarball"]) for v in picked]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def roundtrip(name: str, raw: bytes, enc, dec) -> tuple[int, float, float]:
    t0 = time.perf_counter()
    c = enc(raw)
    t1 = time.perf_counter()
    back = dec(c)
    t2 = time.perf_counter()
    if sha(back) != sha(raw):
        raise RuntimeError(f"{name}: round trip changed the bytes")
    return len(c), t1 - t0, t2 - t1


CODECS = {
    "gzip-9": (lambda b: gzip.compress(b, 9, mtime=0), gzip.decompress),
    "zstd-3": (
        lambda b: zstd.ZstdCompressor(level=3).compress(b),
        lambda c: zstd.ZstdDecompressor().decompress(c),
    ),
    "zstd-19": (
        lambda b: zstd.ZstdCompressor(level=19).compress(b),
        lambda c: zstd.ZstdDecompressor().decompress(c),
    ),
    "xz-9": (lambda b: lzma.compress(b, preset=9), lzma.decompress),
}


def main() -> None:
    names = [row["package"] for row in csv.DictReader(PACKAGES.open())]
    work = Path(tempfile.mkdtemp(prefix="npm-sizing-"))
    total = 0
    corpus: dict[str, list[tuple[str, bytes]]] = {}
    failures = []
    try:
        for pkg in names:
            if total >= CAP_BYTES:
                break
            try:
                vs = versions(pkg)
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                failures.append((pkg, repr(exc)))
                continue
            for v, url in vs:
                if total >= CAP_BYTES:
                    break
                try:
                    tgz = get(url)
                except Exception as exc:  # noqa: BLE001
                    failures.append((f"{pkg}@{v}", repr(exc)))
                    continue
                (work / f"{len(corpus)}_{len(corpus.get(pkg, []))}.tgz").write_bytes(tgz)
                corpus.setdefault(pkg, []).append((v, tgz))
                total += len(tgz)
                time.sleep(0.05)

        per_tarball = {k: 0 for k in ["published", "raw", *CODECS]}
        speed = {k: [0, 0.0, 0.0] for k in CODECS}  # raw bytes, compress s, decompress s
        rows = []
        seen: set[str] = set()
        file_bytes = dup_bytes = 0
        for pkg, items in corpus.items():
            raws = []
            pub = 0
            for _, tgz in items:
                raw = gzip.decompress(tgz)
                raws.append(raw)
                pub += len(tgz)
                per_tarball["published"] += len(tgz)
                per_tarball["raw"] += len(raw)
                for name, (enc, dec) in CODECS.items():
                    size, tc, td = roundtrip(name, raw, enc, dec)
                    per_tarball[name] += size
                    speed[name][0] += len(raw)
                    speed[name][1] += tc
                    speed[name][2] += td
                with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                    for m in tf.getmembers():
                        if not m.isfile():
                            continue
                        f = tf.extractfile(m)
                        data = f.read() if f else b""
                        h = sha(data)
                        file_bytes += len(data)
                        if h in seen:
                            dup_bytes += len(data)
                        seen.add(h)
            solid = b"".join(raws)
            z_long = zstd.ZstdCompressor(
                level=19,
                compression_params=zstd.ZstdCompressionParameters.from_level(19, window_log=27),
            ).compress(solid)
            if sha(zstd.ZstdDecompressor(max_window_size=2**27).decompress(z_long)) != sha(solid):
                raise RuntimeError("solid zstd round trip")
            x_solid = lzma.compress(solid, preset=9)
            if sha(lzma.decompress(x_solid)) != sha(solid):
                raise RuntimeError("solid xz round trip")
            rows.append(
                {
                    "package": pkg,
                    "versions": len(items),
                    "published_bytes": pub,
                    "raw_bytes": len(solid),
                    "solid_zstd19_long_bytes": len(z_long),
                    "solid_xz9_bytes": len(x_solid),
                }
            )

        # dictionary: train on latest tarballs of every other package, test on the rest
        latest = [gzip.decompress(items[-1][1]) for items in corpus.values()]
        train, test = latest[0::2], latest[1::2]
        dict_data = zstd.train_dictionary(110 * 1024, train)
        plain = sum(len(zstd.ZstdCompressor(level=19).compress(b)) for b in test)
        with_dict = 0
        cctx = zstd.ZstdCompressor(level=19, dict_data=dict_data)
        dctx = zstd.ZstdDecompressor(dict_data=dict_data)
        for b in test:
            c = cctx.compress(b)
            if sha(dctx.decompress(c)) != sha(b):
                raise RuntimeError("dictionary round trip")
            with_dict += len(c)
        test_pub = sum(len(items[-1][1]) for i, items in enumerate(corpus.values()) if i % 2 == 1)

        published = per_tarball["published"]
        summary = {
            "date": time.strftime("%Y-%m-%d"),
            "python": platform.python_version(),
            "zstandard": zstd.__version__,
            "packages": len(corpus),
            "tarballs": sum(len(v) for v in corpus.values()),
            "failures": failures,
            "published_tgz_bytes": published,
            "raw_tar_bytes": per_tarball["raw"],
            "per_tarball_bytes": per_tarball,
            "per_tarball_vs_published": {k: per_tarball[k] / published for k in CODECS},
            "solid_by_package_vs_published": {
                "zstd19_long": sum(r["solid_zstd19_long_bytes"] for r in rows) / published,
                "xz9": sum(r["solid_xz9_bytes"] for r in rows) / published,
            },
            "whole_file_dedup_share_of_file_bytes": dup_bytes / file_bytes if file_bytes else 0.0,
            "dictionary": {
                "test_tarballs": len(test),
                "published_bytes": test_pub,
                "zstd19_bytes": plain,
                "zstd19_dict_bytes": with_dict,
                "dict_vs_plain": with_dict / plain,
                "dict_vs_published": with_dict / test_pub,
            },
            "speed_mb_per_s": {
                k: {"compress": v[0] / 2**20 / v[1], "decompress": v[0] / 2**20 / v[2]}
                for k, v in speed.items()
            },
        }
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "npm_sizing.json").write_text(json.dumps(summary, indent=2) + "\n")
        with (OUT / "npm_sizing_packages.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(json.dumps(summary, indent=2))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
