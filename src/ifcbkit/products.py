"""
Product file discovery and parsing for IFCB derived data.

Helpers for locating derived product files alongside raw data:
- find_product_file: recursive search
- list_product_files: pattern-matched listing
- Convenience: blob_path, class_scores_path, features_path
- Readers for blobs, features, and v3 class scores

Both sync and async discovery APIs are provided. Readers are sync-only.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

import aiofiles.os as aios
import aiofiles.ospath as aiopath


@dataclass(slots=True)
class ClassScoresRows:
    """Class score rows for one bin."""

    class_names: list[str]
    rows: list[tuple[int, dict[str, float]]]


def _parse_scalar(value: str) -> int | float:
    try:
        return int(value)
    except ValueError:
        return float(value)


def _require_fieldnames(fieldnames: list[str] | None, context: str) -> list[str]:
    if not fieldnames:
        raise ValueError(f"{context} is missing a header row.")
    return fieldnames


def _resolve_roi_field(fieldnames: list[str], context: str) -> str:
    for candidate in ("roi_number", "roiNumber"):
        if candidate in fieldnames:
            return candidate
    raise ValueError(
        f"{context} is missing an ROI number column. Expected one of: "
        f"roi_number, roiNumber."
    )


# --- Async discovery API ---

async def async_find_product_file(directory, filename, exhaustive=False):
    """Recursively search for a product file by name.

    :param directory: root directory to search
    :param filename: the filename to find
    :param exhaustive: if False, only recurse into directories whose name
        appears in the filename (faster). If True, search all subdirs.
    :returns: full path to the file, or None
    """
    candidate = os.path.join(directory, filename)
    if await aiopath.exists(candidate):
        return candidate

    try:
        names = await aios.listdir(directory)
    except FileNotFoundError:
        return None

    for name in names:
        path = os.path.join(directory, name)
        if await aiopath.isdir(path):
            if not exhaustive and name not in filename:
                continue
            result = await async_find_product_file(path, filename, exhaustive=exhaustive)
            if result is not None:
                return result
        elif name == filename:
            return path

    return None


async def async_list_product_files(directory, regex):
    """Async generator yielding paths to product files matching a regex.

    :param directory: root directory to search
    :param regex: regex pattern to match filenames against
    """
    try:
        names = await aios.listdir(directory)
    except FileNotFoundError:
        return

    for name in names:
        path = os.path.join(directory, name)
        if await aiopath.isdir(path):
            async for p in async_list_product_files(path, regex):
                yield p
        elif re.match(regex, name):
            yield path


async def async_product_path(directory, filename, exhaustive=False):
    """Find a product file or raise FileNotFoundError."""
    path = await async_find_product_file(directory, filename, exhaustive=exhaustive)
    if not path:
        raise FileNotFoundError(f"Product file {filename} not found in {directory}")
    return path


async def async_blob_path(directory, pid, version=4):
    """Find the blob ZIP file for a given PID."""
    filename = f"{pid}_blobs_v{version}.zip"
    return await async_product_path(directory, filename)


async def async_class_scores_path(directory, pid):
    """Find the v3 class scores HDF5 file for a given PID."""
    filename = f"{pid}_class.h5"
    return await async_product_path(directory, filename)


async def async_features_path(directory, pid, version=4):
    """Find the features CSV file for a given PID."""
    filename = f"{pid}_fea_v{version}.csv"
    return await async_product_path(directory, filename)


# --- Sync discovery API ---

def sync_find_product_file(directory, filename, exhaustive=False):
    """Recursively search for a product file by name.

    :param directory: root directory to search
    :param filename: the filename to find
    :param exhaustive: if False, only recurse into directories whose name
        appears in the filename (faster). If True, search all subdirs.
    :returns: full path to the file, or None
    """
    candidate = os.path.join(directory, filename)
    if os.path.exists(candidate):
        return candidate

    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return None

    for name in names:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            if not exhaustive and name not in filename:
                continue
            result = sync_find_product_file(path, filename, exhaustive=exhaustive)
            if result is not None:
                return result
        elif name == filename:
            return path

    return None


def sync_list_product_files(directory, regex):
    """Generator yielding paths to product files matching a regex.

    :param directory: root directory to search
    :param regex: regex pattern to match filenames against
    """
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return

    for name in names:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            yield from sync_list_product_files(directory=path, regex=regex)
        elif re.match(regex, name):
            yield path


def sync_product_path(directory, filename, exhaustive=False):
    """Find a product file or raise FileNotFoundError."""
    path = sync_find_product_file(directory, filename, exhaustive=exhaustive)
    if not path:
        raise FileNotFoundError(f"Product file {filename} not found in {directory}")
    return path


def sync_blob_path(directory, pid, version=4):
    """Find the blob ZIP file for a given PID."""
    filename = f"{pid}_blobs_v{version}.zip"
    return sync_product_path(directory, filename)


def sync_class_scores_path(directory, pid):
    """Find the v3 class scores HDF5 file for a given PID."""
    filename = f"{pid}_class.h5"
    return sync_product_path(directory, filename)


def sync_features_path(directory, pid, version=4):
    """Find the features CSV file for a given PID."""
    filename = f"{pid}_fea_v{version}.csv"
    return sync_product_path(directory, filename)


# --- Parsing API ---

def read_blobs(path: str | os.PathLike[str]):
    """Yield ``(roi_id, png_bytes)`` for every blob in the archive."""
    with ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".png"):
                continue
            roi_id = Path(name).name.removesuffix(".png")
            yield roi_id, zf.read(name)


def read_features(
    path: str | os.PathLike[str],
) -> list[tuple[int, dict[str, int | float]]]:
    """Read IFCB features CSV rows as ``(roi_number, feature_dict)`` pairs."""
    rows: list[tuple[int, dict[str, int | float]]] = []
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = _require_fieldnames(reader.fieldnames, f"Features file {path}")
        roi_field = _resolve_roi_field(fieldnames, f"Features file {path}")

        for row in reader:
            roi_number_raw = row.get(roi_field)
            if roi_number_raw in (None, ""):
                raise ValueError(f"Features file {path} contains a row with no ROI number.")

            values: dict[str, int | float] = {}
            for key, value in row.items():
                if key == roi_field or value in (None, ""):
                    continue
                values[key] = _parse_scalar(value)
            rows.append((int(roi_number_raw), values))
    return rows


def read_class_scores(
    path: str | os.PathLike[str],
) -> ClassScoresRows:
    """Read a v3 IFCB class scores HDF5 file."""
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "read_class_scores requires h5py; install with `pip install ifcbkit[hdf5]`"
        ) from exc

    with h5py.File(path, "r") as handle:
        scores = handle["output_scores"][:]
        class_names = [label.decode("ascii") for label in handle["class_labels"][:]]
        roi_numbers = handle["roi_numbers"][:]

    rows: list[tuple[int, dict[str, float]]] = []
    for roi_number, score_row in zip(roi_numbers, scores, strict=True):
        rows.append(
            (
                int(roi_number),
                {
                    class_name: float(score)
                    for class_name, score in zip(class_names, score_row, strict=True)
                },
            )
        )

    return ClassScoresRows(class_names=class_names, rows=rows)
