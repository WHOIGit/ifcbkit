"""
QC for derived products: features CSVs, class score files, blob archives.

The readers in :mod:`ifcbkit.products` are strict by design — they raise on the
first bad row, which is what a consumer wants. QC needs the opposite: keep
going and report *which* row is bad. So these checks do their own tolerant pass
over each container instead of instrumenting the readers.

That is a second reader, and second readers drift. What keeps these two honest
is an invariant the test suite enforces in both directions: if QC reports no
error for a product file, the strict reader must not raise on it.

Products are rarely stored next to the raw data. The common layout gives each
product type its own root — ``.../features/D20130526/...``,
``.../blobs/2013/D20130526/...`` — so every entry point here takes either one
directory or a per-product mapping (``product_dirs``), and locates a bin's file
by the day/year convention (:func:`candidate_directories`) before falling back
to a recursive search.
"""

import csv
import io
import math
import os
import re
from zipfile import BadZipFile, ZipFile

from PIL import Image

from ..identifiers import bin_day_dir, bin_year, parse_roi_id
from ..products import sync_list_product_files
from .model import Cost, Report, cost_allows
from .registry import PRODUCTS as PRODUCTS_GROUP
from .registry import finding, note_opt_in_skips, resolve_opt_ins

FEATURES = 'features'
CLASS = 'class'
BLOBS = 'blobs'
PRODUCTS = (FEATURES, CLASS, BLOBS)

# Versions this library knows how to read. The readers in ifcbkit.products
# take a version as a default argument rather than consulting a registry, so
# an unknown version is worth a warning even when the file opens.
KNOWN_VERSIONS = {
    FEATURES: (2, 3, 4),
    BLOBS: (2, 3, 4),
    CLASS: (3,),
}

# Filename patterns. The class scores file carries no version in the v3
# naming, so a bare _class.h5 is version 3 by convention.
_PATTERNS = {
    FEATURES: r'_fea_v(?P<version>\d+)\.csv$',
    BLOBS: r'_blobs_v(?P<version>\d+)\.zip$',
    CLASS: r'_class(_v(?P<version>\d+))?\.h5$',
}

# The column names ifcbkit.products accepts for the ROI number.
ROI_COLUMNS = ('roi_number', 'roiNumber')

# Datasets a v3 class scores file must have.
CLASS_DATASETS = ('output_scores', 'class_labels', 'roi_numbers')


def candidate_directories(root, bin_id: str) -> list:
    """Return the directories one bin's products could be in, in search order.

    A product root is normally organized the way raw data is — flat, by day, or
    by year and then day. Looking in those places directly is what lets a big
    product root be used without walking all of it.

    :param root: the root directory for a product type
    :param bin_id: the bin ID
    :returns: directory paths, nearest-convention first
    """
    root = str(root)
    candidates = [root]
    try:
        day_dir = bin_day_dir(bin_id)
        year = str(bin_year(bin_id))
    except ValueError:
        return candidates
    for parts in ((day_dir,), (year, day_dir), (year,)):
        candidates.append(os.path.join(root, *parts))
    return candidates


def product_root(product: str, directory, product_dirs) -> str | None:
    """Return the directory to search for one product type.

    :param product: 'features', 'class', or 'blobs'
    :param directory: the fallback directory for products with no own root
    :param product_dirs: optional ``{product: directory}`` mapping
    :returns: the directory, or None if neither was given
    """
    if product_dirs and product_dirs.get(product) is not None:
        return str(product_dirs[product])
    return None if directory is None else str(directory)


def _matches_in(directory, pattern) -> list:
    """Return matching paths in one directory, without recursing."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return [os.path.join(directory, name) for name in sorted(names)
            if re.match(pattern, name)]


def _versioned(product: str, path: str, pattern: str) -> tuple:
    """Return ``(path, version)``, reading the version out of the filename."""
    match = re.match(pattern, os.path.basename(path))
    declared = match.group('version') if match else None
    return path, int(declared) if declared else _default_version(product)


def _find_product(root, bin_id: str, product: str, *, search: bool) -> tuple | None:
    """Locate one product file for one bin.

    Convention first, recursive search only as a fallback. When several versions
    are present the highest one wins, so discovery does not depend on directory
    listing order.
    """
    pattern = re.escape(bin_id) + _PATTERNS[product]
    paths = []
    for directory in candidate_directories(root, bin_id):
        paths = _matches_in(directory, pattern)
        if paths:
            break
    if not paths and search:
        paths = sorted(sync_list_product_files(str(root), pattern))
    if not paths:
        return None
    return max((_versioned(product, path, pattern) for path in paths),
               key=lambda pair: pair[1])


def find_products(directory, bin_id: str, *, product_dirs=None,
                  search: bool = True) -> dict:
    """Locate this bin's product files, whatever version they are.

    :param directory: directory to search for products that have no entry in
      ``product_dirs``; None to search only the mapped roots
    :param bin_id: the bin ID
    :param product_dirs: ``{product: directory}`` for the usual layout where
      each product type has a root of its own
    :param search: fall back to a recursive walk of a root when the day/year
      conventions do not turn the file up. Pass False on large archives.
    :returns: ``{product: (path, version)}`` for the products that are present
    """
    found = {}
    for product in _PATTERNS:
        root = product_root(product, directory, product_dirs)
        if root is None:
            continue
        located = _find_product(root, bin_id, product, search=search)
        if located is not None:
            found[product] = located
    return found


def _default_version(product: str) -> int:
    """Return the version implied by a filename that declares none."""
    return KNOWN_VERSIONS[product][-1]


def _check_presence(found, expect, report, subject, roots) -> None:
    """Report expected-but-absent products and unknown versions."""
    for product in expect:
        if product not in found:
            report.add(finding(
                'product_missing', subject, product=product,
                searched=roots.get(product) or '(no directory given)'))

    for product, (path, version) in found.items():
        if version not in KNOWN_VERSIONS[product]:
            report.add(finding(
                'product_unexpected_version', subject, path=path,
                product=product, version=version,
                known=', '.join(str(v) for v in KNOWN_VERSIONS[product])))


def _is_numeric(value: str) -> bool:
    """Return True if the value parses the way ``products._parse_scalar`` does."""
    try:
        int(value)
    except ValueError:
        try:
            float(value)
        except ValueError:
            return False
    return True


def _check_features(path, subject, targets, report) -> None:
    """Tolerant pass over a features CSV."""
    try:
        with open(path, newline='') as handle:
            rows = list(csv.reader(handle))
    except OSError as e:
        report.add(finding(
            'product_container_corrupt', subject, path=path,
            product=FEATURES, error=str(e)))
        return

    if not rows:
        report.add(finding('features_missing_header', subject, path=path))
        return

    header = rows[0]
    roi_column = next((c for c in ROI_COLUMNS if c in header), None)
    if roi_column is None:
        report.add(finding(
            'features_missing_roi_column', subject, path=path,
            columns=', '.join(header)))
        return
    roi_index = header.index(roi_column)

    seen = set()
    duplicates = []
    for number, fields in enumerate(rows[1:], start=2):
        if len(fields) != len(header):
            report.add(finding(
                'features_ragged_rows', subject, path=path,
                row=number, n_fields=len(fields), n_columns=len(header)))
        if roi_index >= len(fields) or not fields[roi_index].strip():
            report.add(finding(
                'features_empty_roi_number', subject, path=path, row=number))
            continue

        roi_value = fields[roi_index].strip()
        try:
            roi_number = int(roi_value)
        except ValueError:
            report.add(finding(
                'features_non_numeric', subject, path=path,
                row=number, column=roi_column, value=roi_value))
            continue
        if roi_number in seen:
            duplicates.append(roi_number)
        seen.add(roi_number)

        for column, value in zip(header, fields):
            if column == roi_column or not value.strip():
                continue
            if not _is_numeric(value.strip()):
                report.add(finding(
                    'features_non_numeric', subject, path=path,
                    row=number, column=column, value=value.strip()))

    if duplicates:
        report.add(finding(
            'features_duplicate_rois', subject, path=path,
            count=len(set(duplicates)), example=min(duplicates)))

    _check_coverage(
        seen, targets, subject, path, report,
        coverage_code='features_roi_coverage',
        extra_code='features_roi_not_in_bin')


def _check_coverage(product_rois, targets, subject, path, report, *,
                    coverage_code, extra_code) -> None:
    """Compare a product's ROI numbers against the bin's targets.

    :param product_rois: ROI numbers the product covers
    :param targets: the bin's target numbers, or None if they are unknown
    """
    if targets is None:
        report.skipped[coverage_code] = 'the bin targets were not supplied'
        if extra_code:
            report.skipped[extra_code] = 'the bin targets were not supplied'
        return

    targets = set(targets)
    extra = sorted(product_rois - targets)
    if extra and extra_code:
        report.add(finding(
            extra_code, subject, path=path,
            count=len(extra), example=extra[0]))

    covered = len(product_rois & targets)
    if covered < len(targets) or (extra and not extra_code):
        # ``extra`` is carried on every coverage finding: the class scores
        # check has no separate not-in-bin code, so its message names it.
        report.add(finding(
            coverage_code, subject, path=path,
            covered=covered, total=len(targets), extra=len(extra)))


def _check_class_scores(path, subject, targets, report) -> None:
    """Tolerant pass over a v3 class scores HDF5 file."""
    try:
        import h5py
    except ImportError:
        for code in ('class_missing_dataset', 'class_shape_mismatch',
                     'class_bad_values', 'class_roi_mismatch'):
            report.skipped[code] = 'h5py is not installed'
        return

    try:
        with h5py.File(path, 'r') as handle:
            missing = [name for name in CLASS_DATASETS if name not in handle]
            for name in missing:
                report.add(finding(
                    'class_missing_dataset', subject, path=path, dataset=name))
            if missing:
                return
            scores = handle['output_scores'][:]
            labels = handle['class_labels'][:]
            roi_numbers = handle['roi_numbers'][:]
    except OSError as e:
        report.add(finding(
            'product_container_corrupt', subject, path=path,
            product=CLASS, error=str(e)))
        return

    shape = tuple(scores.shape)
    if len(shape) != 2 or shape[0] != len(roi_numbers) or shape[1] != len(labels):
        report.add(finding(
            'class_shape_mismatch', subject, path=path,
            scores_shape='x'.join(str(d) for d in shape),
            n_labels=len(labels), n_rois=len(roi_numbers)))
        return

    bad = [int(roi_numbers[i]) for i, row in enumerate(scores)
           if any(not math.isfinite(float(value)) for value in row)]
    if bad:
        report.add(finding(
            'class_bad_values', subject, path=path,
            count=len(bad), example=bad[0]))

    _check_coverage(
        {int(n) for n in roi_numbers}, targets, subject, path, report,
        coverage_code='class_roi_mismatch', extra_code=None)


def _check_blobs(path, bin_id, targets, report) -> None:
    """Tolerant pass over a blob ZIP archive."""
    subject = bin_id
    try:
        with ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith('.png')]
            roi_numbers, duplicates = _check_blob_names(
                names, bin_id, subject, path, report)
            for name in names:
                roi_id = os.path.basename(name).removesuffix('.png')
                try:
                    with Image.open(io.BytesIO(archive.read(name))) as image:
                        image.load()
                except Exception as e:  # PIL raises a variety of types here
                    report.add(finding(
                        'blobs_png_decode_failure', subject, path=path,
                        roi_id=roi_id, error=f'{type(e).__name__}: {e}'))
    except (BadZipFile, OSError) as e:
        report.add(finding(
            'product_container_corrupt', subject, path=path,
            product=BLOBS, error=str(e)))
        return

    if duplicates:
        report.add(finding(
            'blobs_duplicate_members', subject, path=path,
            count=len(duplicates), example=sorted(duplicates)[0]))

    _check_coverage(
        roi_numbers, targets, subject, path, report,
        coverage_code='blobs_roi_coverage', extra_code=None)


def _check_blob_names(names, bin_id, subject, path, report) -> tuple[set, set]:
    """Validate archive member names as ROI IDs of this bin.

    :returns: ``(roi_numbers, duplicate_roi_ids)``
    """
    roi_numbers: set = set()
    seen: set = set()
    duplicates: set = set()
    for name in names:
        roi_id = os.path.basename(name).removesuffix('.png')
        try:
            member_bin, target = parse_roi_id(roi_id)
        except ValueError:
            report.add(finding(
                'blobs_bad_roi_id', subject, path=path, member=roi_id))
            continue
        if member_bin != bin_id:
            report.add(finding(
                'blobs_pid_mismatch', subject, path=path,
                member=roi_id, member_bin=member_bin))
            continue
        if roi_id in seen:
            duplicates.add(roi_id)
        seen.add(roi_id)
        roi_numbers.add(target)
    return roi_numbers, duplicates


def check_products(directory, bin_id: str, *, cost=Cost.FULL, expect=(),
                   targets=None, report=None, product_dirs=None,
                   search: bool = True, enable=()) -> Report:
    """Check a bin's derived products for integrity.

    Products usually live outside the raw data tree, one root per product type.
    Pass ``product_dirs`` for that layout; ``directory`` covers the types it
    does not name.

    :param directory: directory to look in for products with no entry in
      ``product_dirs``; None to check only the mapped roots
    :param bin_id: the bin ID
    :param cost: I/O budget; containers are only opened at ``Cost.FULL``
    :param expect: products that must be present ('features', 'class',
      'blobs'); ``product_missing`` fires only for these
    :param targets: the bin's target numbers, for coverage checks; without
      them the coverage checks are recorded as skipped
    :param report: an existing report to add to, instead of a new one
    :param product_dirs: ``{product: directory}``, a root per product type
    :param search: fall back to a recursive walk of a root; see
      :func:`find_products`
    :param enable: opt-in check codes to run, or ``'all'``; see
      :data:`ifcbkit.qc.registry.OPT_IN_CHECKS`
    :returns: the :class:`Report`
    """
    cost = Cost(cost)
    enabled = resolve_opt_ins(enable)
    report = report if report is not None else Report(subject=bin_id, cost=cost)
    note_opt_in_skips(report, (PRODUCTS_GROUP,), enabled)

    found = find_products(
        directory, bin_id, product_dirs=product_dirs, search=search)
    roots = {product: product_root(product, directory, product_dirs)
             for product in _PATTERNS}
    _check_presence(found, expect, report, bin_id, roots)

    if not cost_allows(cost, Cost.FULL):
        return report

    if FEATURES in found:
        _check_features(found[FEATURES][0], bin_id, targets, report)
    if CLASS in found:
        _check_class_scores(found[CLASS][0], bin_id, targets, report)
    if BLOBS in found:
        _check_blobs(found[BLOBS][0], bin_id, targets, report)
    return report
