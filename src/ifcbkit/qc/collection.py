"""
QC across a whole directory tree of raw IFCB data.

The most important check here is ``fileset_incomplete``, and it is the reason
this module walks the tree itself rather than calling
:func:`ifcbkit.fileset.sync_list_filesets`: that generator only yields complete
.hdr/.adc/.roi triplets, and :func:`ifcbkit.fileset.sync_find_fileset` returns
``None`` for a partial one. Both are correct for reading data and useless for
reporting on it — a half-copied bin is indistinguishable from a bin that was
never there. So this pass groups every directory entry by basename and reports
what is missing.

The other checks are about the shape of the collection: bins in the wrong day
directory, the same bin ID in two places, filesets a listing filter would drop
silently, and corrections with nothing to correct.
"""

import os
from collections import defaultdict

from ..fileset import (
    ADCMOD_EXT,
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    make_fileset_filter,
    validate_path,
)
from ..identifiers import bin_day_dir, bin_instrument_id, bin_timestamp
from .model import Cost, Report
from .raw import ROI_EXT
from .registry import COLLECTION, finding, note_opt_in_skips, resolve_opt_ins

REQUIRED_EXTENSIONS = ('hdr', 'adc', 'roi')

# Files that legitimately live alongside raw data without being raw data.
IGNORED_NAMES = ('.DS_Store', 'Thumbs.db')


def _classify_entries(filenames):
    """Group a directory's filenames into filesets and strays.

    :returns: ``({basename: set_of_extensions}, [stray_filenames])``
    """
    by_basename = defaultdict(set)
    strays = []
    for name in filenames:
        if name in IGNORED_NAMES:
            continue
        basename, _, ext = name.rpartition('.')
        if basename and ext in REQUIRED_EXTENSIONS:
            by_basename[basename].add(ext)
        else:
            strays.append(name)
    return by_basename, strays


def walk_filesets(root, *, exclude=DEFAULT_EXCLUDE, include=DEFAULT_INCLUDE,
                  report=None):
    """Walk a raw data tree, yielding every fileset including partial ones.

    :param root: root directory of the raw data tree
    :param exclude: directory names to skip
    :param include: directory names to enter regardless of the bin ID
    :param report: optional report, to record skipped directories and strays
    :yields: ``(directory, bin_id, extensions_present)``
    """
    root = os.path.normpath(str(root))
    for directory, dirnames, filenames in os.walk(root):
        for name in sorted(set(dirnames) & set(exclude)):
            if report is not None:
                report.add(finding(
                    'excluded_by_path_rules', root,
                    path=os.path.join(directory, name), rule='exclude'))
        dirnames[:] = sorted(d for d in dirnames if d not in exclude)

        by_basename, strays = _classify_entries(filenames)
        if report is not None and strays:
            report.add(finding(
                'stray_files', root, path=directory,
                count=len(strays), example=sorted(strays)[0]))

        reldir = '' if directory == root else directory[len(root) + 1:]
        for bin_id in sorted(by_basename):
            if not validate_path(os.path.join(reldir, bin_id + '.hdr'),
                                 include=include, exclude=exclude):
                if report is not None:
                    report.add(finding(
                        'excluded_by_path_rules', root,
                        path=os.path.join(directory, bin_id),
                        rule='include'))
                continue
            yield directory, bin_id, by_basename[bin_id]

        if report is not None and not by_basename and not dirnames:
            report.add(finding('empty_day_dir', root, path=directory))


def _check_completeness(root, filesets, report, roi_optional=False) -> None:
    """Report filesets with some but not all of .hdr/.adc/.roi.

    With ``roi_optional``, a fileset whose *only* absent file is the .roi is not
    incomplete — that is a bin whose image data has not arrived yet. One still
    missing its .hdr or .adc is reported either way, which is the distinction
    ``--ignore fileset_incomplete`` could not make.
    """
    optional = (ROI_EXT,) if roi_optional else ()
    for directory, bin_id, extensions in filesets:
        missing = [ext for ext in REQUIRED_EXTENSIONS
                   if ext not in extensions and ext not in optional]
        if missing:
            report.add(finding(
                'fileset_incomplete', root,
                path=os.path.join(directory, bin_id), bin_id=bin_id,
                present=', '.join(f'.{e}' for e in sorted(extensions)),
                missing=', '.join(f'.{e}' for e in missing)))


def _check_duplicates(root, filesets, report) -> None:
    """Report bin IDs that appear in more than one directory."""
    directories = defaultdict(list)
    for directory, bin_id, _ in filesets:
        directories[bin_id].append(directory)
    for bin_id, dirs in sorted(directories.items()):
        if len(dirs) > 1:
            report.add(finding(
                'duplicate_pid', root, bin_id=bin_id,
                count=len(dirs), directories=', '.join(sorted(dirs))))


def _check_day_dirs(root, filesets, report) -> None:
    """Report bins whose containing directory is not the one their ID implies.

    A directory named for the bin itself is not a mismatch: that is a layout
    ifcbkit supports directly (see :func:`ifcbkit.qc.raw.resolve_fileset`).
    """
    for directory, bin_id, _ in filesets:
        actual = os.path.basename(directory)
        if actual == bin_id:
            continue
        try:
            expected = bin_day_dir(bin_id)
        except ValueError:
            continue  # unparseable IDs are reported per-bin, not here
        if actual != expected:
            report.add(finding(
                'day_dir_mismatch', root, path=directory,
                bin_id=bin_id, actual=actual, expected=expected))


def _check_filter_drops(root, filesets, report, *, start_time, end_time,
                        instrument) -> None:
    """Report filesets a listing filter would drop without saying so."""
    fs_filter = make_fileset_filter(start_time, end_time, instrument)
    if fs_filter is None:
        return
    name = 'time' if instrument is None else (
        'instrument' if start_time is None and end_time is None
        else 'time and instrument')
    for _, bin_id, _ in filesets:
        if not fs_filter(bin_id):
            report.add(finding(
                'dropped_by_filter', root, bin_id=bin_id, filter_name=name))


def _check_missing_days(root, filesets, report) -> None:
    """Report days between the first and last bin that hold no data at all."""
    days = set()
    for _, bin_id, _ in filesets:
        try:
            days.add(bin_timestamp(bin_id).date())
        except ValueError:
            continue
    if len(days) < 2:
        return
    first, last = min(days), max(days)
    span = (last - first).days + 1
    absent = span - len(days)
    if absent:
        report.add(finding(
            'missing_days', root, count=absent,
            first=first.isoformat(), last=last.isoformat()))


def _check_instruments(root, filesets, report) -> None:
    """Report directories holding bins from more than one instrument."""
    by_directory = defaultdict(set)
    for directory, bin_id, _ in filesets:
        try:
            by_directory[directory].add(bin_instrument_id(bin_id))
        except ValueError:
            continue
    for directory, instruments in sorted(by_directory.items()):
        if len(instruments) > 1:
            report.add(finding(
                'mixed_instruments', root, path=directory,
                instruments=', '.join(str(i) for i in sorted(instruments))))


def _check_adcmod_orphans(root, filesets, adcmod_root, report) -> None:
    """Report corrections in the adcmod tree with no raw fileset to correct."""
    known = {bin_id for _, bin_id, _ in filesets}
    orphans = []
    for directory, _, filenames in os.walk(str(adcmod_root)):
        for name in filenames:
            if not name.endswith(ADCMOD_EXT):
                continue
            bin_id = name[:-len(ADCMOD_EXT)]
            if bin_id not in known:
                orphans.append(os.path.join(directory, name))
    if orphans:
        report.add(finding(
            'adcmod_orphans', root, path=str(adcmod_root),
            count=len(orphans), example=os.path.basename(sorted(orphans)[0])))


def check_collection(root, *, cost=Cost.STAT, exclude=DEFAULT_EXCLUDE,
                     include=DEFAULT_INCLUDE, start_time=None, end_time=None,
                     instrument=None, enable=(), roi_optional=False,
                     adcmod_root=None) -> Report:
    """Check the shape of a raw data collection.

    Per-bin integrity is :func:`ifcbkit.qc.raw.check_fileset`'s job; this
    reports on what the collection as a whole looks like.

    :param root: root directory of the raw data tree
    :param cost: I/O budget; every check here is ``Cost.STAT``
    :param exclude: directory names to skip
    :param include: directory names to enter regardless of the bin ID
    :param start_time: lower bound a listing filter would apply
    :param end_time: upper bound a listing filter would apply
    :param instrument: instrument filter a listing would apply
    :param enable: opt-in check codes to run, or ``'all'``; see
      :data:`ifcbkit.qc.registry.OPT_IN_CHECKS`
    :param roi_optional: do not call a fileset incomplete when the .roi is its
      only absent file; see :func:`ifcbkit.qc.raw.check_fileset`
    :param adcmod_root: the adcmod tree to check for orphaned corrections
    :returns: a :class:`Report` whose subject is the root path
    """
    root = os.path.normpath(str(root))
    enabled = resolve_opt_ins(enable)
    report = Report(subject=root, cost=Cost(cost))
    note_opt_in_skips(report, (COLLECTION,), enabled)

    filesets = list(walk_filesets(
        root, exclude=exclude, include=include, report=report))

    _check_completeness(root, filesets, report, roi_optional)
    _check_duplicates(root, filesets, report)
    _check_day_dirs(root, filesets, report)
    _check_filter_drops(
        root, filesets, report, start_time=start_time, end_time=end_time,
        instrument=instrument)
    _check_missing_days(root, filesets, report)
    if 'mixed_instruments' in enabled:
        _check_instruments(root, filesets, report)
    if adcmod_root is not None and os.path.isdir(str(adcmod_root)):
        _check_adcmod_orphans(root, filesets, adcmod_root, report)

    return report


def list_bins(root, *, exclude=DEFAULT_EXCLUDE, include=DEFAULT_INCLUDE) -> list:
    """Return ``(directory, bin_id)`` for every fileset, complete or not.

    The entry point for checking each bin in a tree: unlike
    :func:`ifcbkit.fileset.sync_list_filesets`, incomplete filesets are
    included, because those are exactly the ones worth reporting on.
    """
    return [(directory, bin_id) for directory, bin_id, _ in
            walk_filesets(root, exclude=exclude, include=include)]
