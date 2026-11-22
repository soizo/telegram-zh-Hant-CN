from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import PipelineError, build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegram-cngov",
        description="Convert Telegram zh-Hans exports to zh-Hant-CN.",
    )
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--rules", type=Path, default=Path("rules.yml"))
    parser.add_argument(
        "--tag",
        help="release tag embedded in the archive name (default: today's vYYYY.MM.DD)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="keep intermediate conversions in this directory",
    )
    args = parser.parse_args(argv)
    try:
        result = build(
            args.output,
            tag=args.tag,
            work_dir=args.work_dir,
            rules=args.rules,
        )
    except PipelineError as error:
        parser.exit(1, f"error: {error}\n")
    print(
        f"wrote {len(result.files)} files, {len(result.import_files)} import files, "
        f"{result.archive.name} and {result.import_archive.name} "
        f"to {result.output} (t2gov {result.t2gov_sha})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
