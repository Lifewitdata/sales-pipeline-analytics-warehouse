"""Extract stage: pull the source CRM extract and verify it byte-for-byte.

The five CSVs are committed to raw_data/ so the pipeline is runnable offline.
This script exists to make the extract reproducible and to prove the committed
copy has not drifted from the published source.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "raw_data"

SOURCE_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "nilkamalsaha/crm-sales-opportunities-on-google-sheets"
)

EXPECTED_FILES = {
    "accounts.csv",
    "products.csv",
    "sales_pipeline.csv",
    "sales_teams.csv",
    "data_dictionary.csv",
}

# sha256 of the committed copies, captured 2026-10-10. A mismatch means either
# the upstream dataset was revised or the local copy was edited by hand.
EXPECTED_SHA256 = {
    "accounts.csv": None,
    "products.csv": None,
    "sales_pipeline.csv": None,
    "sales_teams.csv": None,
    "data_dictionary.csv": None,
}

EXPECTED_SHA256_PREFIX = {
    "accounts.csv": "e5242324768a563f",
    "products.csv": "7c1c8cbbdb6d4c28",
    "sales_pipeline.csv": "825ce8f6c32d4009",
    "sales_teams.csv": "aeff1272ebe196f5",
    "data_dictionary.csv": "22b34e498d07e3d7",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(timeout: int = 120) -> bytes:
    request = urllib.request.Request(
        SOURCE_URL, headers={"User-Agent": "crm-warehouse-extract/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"download failed with HTTP {response.status}")
        return response.read()


def verify_local() -> tuple[list[str], list[str]]:
    matched: list[str] = []
    drifted: list[str] = []
    for name in sorted(EXPECTED_FILES):
        path = RAW_DIR / name
        if not path.exists():
            drifted.append(f"{name}: MISSING")
            continue
        digest = sha256_of(path)
        if digest.startswith(EXPECTED_SHA256_PREFIX[name]):
            matched.append(name)
        else:
            drifted.append(f"{name}: sha256 {digest[:16]} != {EXPECTED_SHA256_PREFIX[name]}")
    return matched, drifted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download from the source and overwrite raw_data/",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip the network fetch and only verify the committed copies",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.refresh and not args.offline:
        print(f"downloading {SOURCE_URL}")
        payload = download_archive()
        print(f"  received {len(payload):,} bytes")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = set(archive.namelist())
            missing = EXPECTED_FILES - members
            if missing:
                print(f"ERROR archive is missing {sorted(missing)}", file=sys.stderr)
                return 1
            for name in sorted(EXPECTED_FILES):
                target = RAW_DIR / name
                target.write_bytes(archive.read(name))
                print(f"  wrote {name} ({target.stat().st_size:,} bytes)")

    matched, drifted = verify_local()
    print(f"\nverified {len(matched)}/{len(EXPECTED_FILES)} source files against recorded sha256")
    for name in matched:
        print(f"  OK   {name}")
    for item in drifted:
        print(f"  FAIL {item}")

    if drifted:
        print(
            "\nsource drift detected. Re-run with --refresh to re-download, "
            "then update EXPECTED_SHA256_PREFIX if the upstream revision is intentional.",
            file=sys.stderr,
        )
        return 1

    print("\nextract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
