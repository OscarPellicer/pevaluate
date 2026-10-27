"""Small helpers shared by the grading, report and marks modules."""
import argparse
import csv
import os
import re
from typing import Optional

import yaml


def safe_name(value) -> str:
    """``value`` reduced to ``[A-Za-z0-9_-]`` for use in file names (``"item"`` if empty)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_") or "item"


def to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_csv_rows(path: str, optional: bool = False, encoding: str = "utf-8", **reader_kwargs) -> list[dict]:
    """Rows of a CSV file as dicts. With ``optional``, a missing (or empty) path gives ``[]``."""
    if optional and (not path or not os.path.exists(path)):
        return []
    with open(path, newline="", encoding=encoding) as f:
        return list(csv.DictReader(f, **reader_kwargs))


def write_yaml(path: str, data) -> None:
    """YAML as written by every pevaluate output: UTF-8, keys in order, long lines unwrapped."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=1000)


def add_hidden_alias(parser: argparse.ArgumentParser, flag: str, dest: str, **kwargs) -> None:
    """Accept an old option spelling (``flag``) for ``dest`` without listing it in ``--help``."""
    parser.add_argument(flag, dest=dest, help=argparse.SUPPRESS, default=argparse.SUPPRESS, **kwargs)
