#!/usr/bin/env python3
"""Batch jieba word segmentation — inserts \\x1e (Record Separator) between tokens.

Used as a pre-processing step before OpenCC conversion so that OpenCC
respects jieba's word boundaries instead of relying solely on its
built-in mmseg segmentation.

Usage:
    python3 jieba_segment.py INPUT_DIR OUTPUT_DIR --dict DICT [--userdict USERDICT]
"""

import argparse
import logging
import os
import sys

# Suppress jieba's noisy debug/info logging
logging.getLogger("jieba").setLevel(logging.WARNING)

import jieba  # noqa: E402

RS = "\x1e"  # Record Separator — used as word-boundary marker


def main():
    parser = argparse.ArgumentParser(description="Batch jieba segmentation")
    parser.add_argument("input_dir", help="Directory containing input files")
    parser.add_argument("output_dir", help="Directory for segmented output")
    parser.add_argument(
        "--dict",
        required=True,
        dest="dict_path",
        help="Path to jieba main dictionary",
    )
    parser.add_argument(
        "--userdict",
        dest="userdict_path",
        help="Path to jieba user dictionary",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"ERROR: input directory does not exist: {args.input_dir}", file=sys.stderr)
        return 1

    # Initialise tokeniser (expensive — done once for all files)
    tokeniser = jieba.Tokenizer(dictionary=args.dict_path)
    tokeniser.initialize()
    if args.userdict_path:
        tokeniser.load_userdict(args.userdict_path)

    os.makedirs(args.output_dir, exist_ok=True)

    for name in sorted(os.listdir(args.input_dir)):
        filepath = os.path.join(args.input_dir, name)
        if not os.path.isfile(filepath):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        tokens = tokeniser.cut(text, cut_all=False)
        segmented = RS.join(tokens)
        with open(os.path.join(args.output_dir, name), "w", encoding="utf-8") as f:
            f.write(segmented)

    return 0


if __name__ == "__main__":
    sys.exit(main())
