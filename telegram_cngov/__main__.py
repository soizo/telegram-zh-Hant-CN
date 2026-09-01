from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import PipelineError, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telegram-cngov",
        description="Convert Telegram zh-Hans exports to zh-Hant-CN.",
    )
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--from",
        dest="from_step",
        type=int,
        choices=range(1, 6),
        default=1,
        help="resume from stage 1-5 (requires --work-dir)",
    )
    parser.add_argument("--metadata", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.from_step > 1 and args.work_dir is None:
        parser.error("--from greater than 1 requires --work-dir")
    try:
        result = run_pipeline(
            args.output,
            work_dir=args.work_dir,
            from_step=args.from_step,
        )
    except PipelineError as error:
        parser.exit(1, f"error: {error}\n")
    if args.metadata is not None:
        args.metadata.parent.mkdir(parents=True, exist_ok=True)
        args.metadata.write_text(
            json.dumps({"t2gov_sha": result.t2gov_sha}) + "\n",
            encoding="utf-8",
        )
    print(f"wrote {len(result.files)} files to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
