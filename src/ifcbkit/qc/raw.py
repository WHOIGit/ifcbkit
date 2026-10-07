"""
QC for a single raw IFCB fileset: .hdr, .adc, .roi (and any .adc.mod).

Everything here is a question about integrity, answered from the files
themselves: are the three files present and non-trivial, does the bin ID
parse and agree with the header, does every ADC line parse, and does every
target's byte range fit inside the .roi file.

ADC and header findings come from the diagnostics channels of
:func:`ifcbkit.adc.iter_adc_targets` and :func:`ifcbkit.header.parse_hdr`,
not from a second parser, so QC cannot disagree with the parse path that
consumers actually use.
"""

import os
from calendar import isleap, monthrange
from dataclasses import dataclass
from datetime import datetime, timezone

from .. import adc as adc_mod
from .. import header as hdr_mod
from .. import roi as roi_mod
from ..fileset import adcmod_path
from ..identifiers import bin_instrument_id, bin_timestamp, parse_bin_id
from .model import Cost, Report, cost_allows
from .registry import (
    ADC,
    ADCMOD,
    HEADER,
    IDENTIFIERS,
    PRESENCE,
    ROI,
    finding,
    note_opt_in_skips,
    resolve_opt_ins,
)

# The catalogue groups check_fileset is responsible for.
RAW_GROUPS = (PRESENCE, IDENTIFIERS, HEADER, ADC, ROI, ADCMOD)

# A fileset smaller than this cannot hold usable data. Ports ifcbdb's MIN_SIZE.
MIN_FILESET_BYTES = 32

# Geometry bounds. Generous on purpose: the check is for values that cannot
# describe an ROI at all, not for values that look unusual for one instrument.
MAX_ROI_DIMENSION = 4096
MAX_ROI_ORIGIN = 8192
MAX_ROI_PIXELS = 16_000_000

# add_target emits a 5-digit suffix, which parse_roi_id then requires.
MAX_TARGET_NUMBER = 99999

# I-style .roi files use 1-based offsets and end with a pad byte, so a few
# bytes are unclaimed in every intact bin. Only a real gap should be reported.
UNACCOUNTED_SLACK_BYTES = 64

# How much of an offending line to quote in a finding message.
MAX_QUOTED_CHARS = 120

# A 1-byte .roi is how older acquisition software recorded "no ROIs".
ROI_SENTINEL_BYTES = 1

# No IFCB data predates the instrument. Used only for a warning.
EARLIEST_PLAUSIBLE = datetime(2005, 1, 1, tzinfo=timezone.utc)

# Header keys that carry the instrument ID and sample time, when present.
HDR_INSTRUMENT_KEY = 'imagerID'
HDR_SAMPLE_TIME_KEY = 'sampleTime'

# How far the header sample time may differ from the bin ID timestamp.
SAMPLE_TIME_TOLERANCE_SECONDS = 2

EXTENSIONS = ('hdr', 'adc', 'roi')
ROI_EXT = 'roi'

# Why an absent .roi was not reported as missing. ROI telemetry can lag the
# .hdr and .adc by hours, so a bin that has not received its image data yet is
# incomplete on purpose — but the ADC-to-ROI checks still could not run, and a
# report must not imply they passed.
ROI_OPTIONAL_REASON = ('the .roi file has not arrived (roi_optional); the '
                       'ADC-to-ROI checks could not run')

# header.py reason -> check code, for the header diagnostics channel. The ADC
# reasons need per-reason detail, so they are mapped in _report_adc_diagnostics.
_HDR_REASON_CODES = {
    hdr_mod.UNRECOGNIZED_FORMAT: 'hdr_unrecognized_format',
    hdr_mod.TRUNCATED: 'hdr_truncated',
    hdr_mod.CAST_FAILURE: 'hdr_cast_failure',
    hdr_mod.COLUMN_COUNT_MISMATCH: 'hdr_column_count_mismatch',
    hdr_mod.MISSING_KEYS: 'hdr_missing_keys',
}


@dataclass(frozen=True, slots=True)
class FilesetPaths:
    """Where the three files of one fileset are, whether or not they exist."""

    bin_id: str
    directory: str
    hdr: str
    adc: str
    roi: str

    def path_for(self, ext: str) -> str:
        """Return the path for one extension ('hdr', 'adc', or 'roi')."""
        return getattr(self, ext)


def resolve_fileset(path, bin_id: str | None = None) -> FilesetPaths:
    """Resolve any reference to a fileset into its three paths.

    Accepts a basepath without extension, any one of the three files, or a
    directory named for the bin it contains.

    :param path: basepath, a .hdr/.adc/.roi path, or a bin-named directory
    :param bin_id: the bin ID, if it differs from the basename
    :returns: a :class:`FilesetPaths`
    """
    path = os.path.normpath(str(path))
    if os.path.isdir(path):
        basepath = os.path.join(path, os.path.basename(path))
    else:
        stem, ext = os.path.splitext(path)
        basepath = stem if ext.lstrip('.') in EXTENSIONS else path
    return FilesetPaths(
        bin_id=bin_id or os.path.basename(basepath),
        directory=os.path.dirname(basepath),
        hdr=basepath + '.hdr',
        adc=basepath + '.adc',
        roi=basepath + '.roi',
    )


def _sizes(paths: FilesetPaths, report: Report, roi_optional=False) -> dict:
    """Stat all three files, reporting what is missing or unreadable.

    :param roi_optional: treat an absent .roi as expected rather than an error;
      see :func:`check_fileset`
    :returns: ``{ext: size_in_bytes or None}``
    """
    sizes = {}
    for ext in EXTENSIONS:
        path = paths.path_for(ext)
        try:
            sizes[ext] = os.path.getsize(path)
        except FileNotFoundError:
            sizes[ext] = None
            if ext == ROI_EXT and roi_optional:
                # Not an error, but not verified either: say so, so that a bin
                # still awaiting its ROI data cannot read as fully checked.
                report.skipped['missing_roi'] = ROI_OPTIONAL_REASON
                continue
            report.add(finding(f'missing_{ext}', paths.bin_id, path=path))
        except OSError as e:
            sizes[ext] = None
            report.add(finding(
                'unreadable_file', paths.bin_id, path=path,
                ext=ext, error=str(e)))
    return sizes


def _check_sizes(paths: FilesetPaths, sizes: dict, report: Report) -> None:
    """Report zero-byte files, trivially small filesets, and empty sentinels."""
    for ext in EXTENSIONS:
        if sizes[ext] == 0:
            report.add(finding(
                'zero_byte_file', paths.bin_id, path=paths.path_for(ext),
                ext=ext))

    if sizes['roi'] == ROI_SENTINEL_BYTES:
        report.add(finding(
            'empty_roi_sentinel', paths.bin_id, path=paths.roi))

    present = [size for size in sizes.values() if size is not None]
    total = sum(present)
    if present and total < MIN_FILESET_BYTES:
        report.add(finding(
            'tiny_fileset', paths.bin_id,
            total_bytes=total, min_bytes=MIN_FILESET_BYTES))


def _range_problem(parsed: dict) -> tuple[str, int, str] | None:
    """Return ``(field, value, reason)`` for the first out-of-range ID field.

    The bin ID regexes constrain digit counts but not meaning, and
    :func:`ifcbkit.identifiers.bin_timestamp` silently rolls day-of-year 0
    into the previous year rather than rejecting it.
    """
    year = parsed['year']
    if 'day_of_year' in parsed:
        doy = parsed['day_of_year']
        days = 366 if isleap(year) else 365
        if doy < 1 or doy > days:
            return 'day_of_year', doy, f'{year} has {days} days'
    else:
        month = parsed['month']
        if month < 1 or month > 12:
            return 'month', month, 'months are 1..12'
        day = parsed['day']
        days = monthrange(year, month)[1]
        if day < 1 or day > days:
            return 'day', day, f'{year}-{month:02d} has {days} days'
    for field, limit in (('hour', 23), ('minute', 59), ('second', 59)):
        value = parsed[field]
        if value > limit:
            return field, value, f'{field} is 0..{limit}'
    return None


def _check_identifiers(paths: FilesetPaths, report: Report) -> dict | None:
    """Check that the bin ID parses, is in range, and matches the basename.

    :returns: the parsed bin ID components, or None if it does not parse (in
      which case every ID-dependent check downstream is skipped)
    """
    basename = os.path.basename(paths.adc)[:-len('.adc')]
    if basename != paths.bin_id:
        report.add(finding(
            'basename_mismatch', paths.bin_id, path=paths.adc,
            basename=basename, bin_id=paths.bin_id))

    try:
        parsed = parse_bin_id(paths.bin_id)
    except ValueError as e:
        report.add(finding(
            'unparseable_bin_id', paths.bin_id, error=str(e)))
        return None

    problem = _range_problem(parsed)
    if problem is not None:
        field, value, reason = problem
        report.add(finding(
            'bin_id_out_of_range', paths.bin_id,
            field=field, value=value, reason=reason))
        return parsed

    timestamp = bin_timestamp(paths.bin_id)
    if timestamp < EARLIEST_PLAUSIBLE or timestamp > datetime.now(timezone.utc):
        report.add(finding(
            'implausible_timestamp', paths.bin_id,
            timestamp=timestamp.isoformat(),
            earliest=EARLIEST_PLAUSIBLE.date().isoformat()))
    return parsed


def _parse_sample_time(value) -> datetime | None:
    """Parse a header sampleTime value into an aware datetime, or None."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _check_header(paths: FilesetPaths, parsed_id: dict | None, report: Report) -> dict:
    """Parse the header through its diagnostics channel and cross-check the PID.

    :returns: the header properties (empty if the header could not be read)
    """
    diagnostics: list = []
    try:
        with open(paths.hdr, 'rb') as f:
            props = hdr_mod.parse_hdr_bytes(f.read(), diagnostics=diagnostics)
    except FileNotFoundError:
        return {}
    except OSError as e:
        report.add(finding(
            'unreadable_file', paths.bin_id, path=paths.hdr,
            ext='hdr', error=str(e)))
        return {}

    for entry in diagnostics:
        detail = {k: v for k, v in entry.items() if k != 'reason'}
        if entry['reason'] == hdr_mod.COLUMN_COUNT_MISMATCH:
            detail.pop('columns', None)
        elif entry['reason'] == hdr_mod.MISSING_KEYS:
            detail = {'missing': ', '.join(detail['missing'])}
        elif entry['reason'] == hdr_mod.CAST_FAILURE:
            detail.pop('error', None)
        report.add(finding(
            _HDR_REASON_CODES[entry['reason']], paths.bin_id,
            path=paths.hdr, **detail))

    if parsed_id is None:
        return props

    if HDR_INSTRUMENT_KEY in props:
        try:
            hdr_instrument = int(str(props[HDR_INSTRUMENT_KEY]).strip())
        except ValueError:
            hdr_instrument = None
        pid_instrument = bin_instrument_id(paths.bin_id)
        if hdr_instrument is not None and hdr_instrument != pid_instrument:
            report.add(finding(
                'hdr_pid_instrument_mismatch', paths.bin_id, path=paths.hdr,
                hdr_instrument=hdr_instrument, pid_instrument=pid_instrument))

    if HDR_SAMPLE_TIME_KEY in props:
        hdr_time = _parse_sample_time(props[HDR_SAMPLE_TIME_KEY])
        pid_time = bin_timestamp(paths.bin_id)
        if hdr_time is not None:
            delta = abs((hdr_time - pid_time).total_seconds())
            if delta > SAMPLE_TIME_TOLERANCE_SECONDS:
                report.add(finding(
                    'hdr_pid_time_mismatch', paths.bin_id, path=paths.hdr,
                    hdr_time=hdr_time.isoformat(),
                    pid_time=pid_time.isoformat(),
                    delta_seconds=int(delta)))
    return props


def _style_of(bin_id: str) -> str:
    """Return 'I' or 'D' — the layout ifcbkit picks from the bin ID alone."""
    return 'I' if bin_id.startswith('I') else 'D'


def _report_adc_diagnostics(paths, diagnostics, cols, report, enabled) -> None:
    """Turn ADC skip diagnostics into findings, aggregating zero-geometry.

    Zero-geometry triggers are counted whether or not anyone asked for them —
    the count is free — but only reported when ``adc_zero_geometry`` is
    enabled, because nearly every real bin has many of them.
    """
    style = _style_of(paths.bin_id)
    required = max(cols.values()) + 1
    zero_geometry = 0
    for entry in diagnostics:
        reason = entry['reason']
        if reason == adc_mod.ZERO_GEOMETRY:
            zero_geometry += 1
        elif reason == adc_mod.SHORT_ROW:
            report.add(finding(
                'adc_column_count_mismatch', paths.bin_id, path=paths.adc,
                line=entry['line'], n_fields=entry['n_fields'],
                style=style, required=required))
        elif reason == adc_mod.BLANK_LINE:
            report.add(finding(
                'adc_blank_line', paths.bin_id, path=paths.adc,
                line=entry['line']))
        else:
            report.add(finding(
                'adc_unparseable_line', paths.bin_id, path=paths.adc,
                line=entry['line'], text=entry['text'][:MAX_QUOTED_CHARS]))

    if zero_geometry and 'adc_zero_geometry' in enabled:
        report.add(finding(
            'adc_zero_geometry', paths.bin_id, path=paths.adc,
            count=zero_geometry))


def _check_adc_layout(paths, diagnostics, cols, props, n_lines, report) -> None:
    """Check the column layout against the data and against the header.

    ifcbkit picks a layout from ``bin_id.startswith('I')`` alone. Two things
    can contradict that choice: rows too short for the chosen layout but long
    enough for the other one, and the header's own ``ADCFileFormat``
    declaration.
    """
    style = _style_of(paths.bin_id)
    short_rows = [d for d in diagnostics if d['reason'] == adc_mod.SHORT_ROW]
    blanks = sum(1 for d in diagnostics if d['reason'] == adc_mod.BLANK_LINE)

    # Every usable line short for this layout, but long enough for the other:
    # the style was misdetected, not the data damaged.
    if short_rows and len(short_rows) == n_lines - blanks:
        other = adc_mod.I_STYLE_COLUMNS if style == 'D' else adc_mod.D_STYLE_COLUMNS
        n_fields = min(d['n_fields'] for d in short_rows)
        if n_fields > max(other.values()):
            report.add(finding(
                'adc_style_misdetected', paths.bin_id, path=paths.adc,
                style=style, n_fields=n_fields,
                reason=f'the {"I" if style == "D" else "D"}-style layout fits'))

    declaration = props.get(hdr_mod.ADC_FILE_FORMAT)
    if not declaration:
        return
    declared = adc_mod.columns_from_declaration(
        hdr_mod.parse_adc_file_format(declaration))
    if declared is None:
        report.skipped['adc_format_declaration_mismatch'] = (
            'the ADCFileFormat declaration does not name all five columns')
        return
    for field, used_index in cols.items():
        if declared[field] != used_index:
            report.add(finding(
                'adc_format_declaration_mismatch', paths.bin_id, path=paths.hdr,
                field=field, declared_index=declared[field],
                used_index=used_index, style=style))


def _check_targets(paths, targets, report) -> None:
    """Check geometry plausibility, trigger order, and ROI ID width."""
    previous_trigger = None
    for record in targets:
        width, height = record['width'], record['height']
        x, y = record['x'], record['y']
        reason = None
        if width > MAX_ROI_DIMENSION or height > MAX_ROI_DIMENSION:
            reason = f'dimensions exceed {MAX_ROI_DIMENSION}px'
        elif width < 0 or height < 0 or x < 0 or y < 0:
            reason = 'negative geometry'
        elif x > MAX_ROI_ORIGIN or y > MAX_ROI_ORIGIN:
            reason = f'origin exceeds {MAX_ROI_ORIGIN}px'
        elif width * height > MAX_ROI_PIXELS:
            reason = f'area exceeds {MAX_ROI_PIXELS} pixels'
        if reason is not None:
            report.add(finding(
                'adc_absurd_geometry', paths.bin_id, path=paths.adc,
                target=record['target'], width=width, height=height,
                x=x, y=y, reason=reason))

        # Consecutive targets may share a trigger — that is how I-style
        # instruments record a stitched pair — but a trigger must not go
        # backwards.
        trigger = record['trigger']
        if previous_trigger is not None and trigger < previous_trigger:
            report.add(finding(
                'adc_target_discontinuity', paths.bin_id, path=paths.adc,
                target=record['target'], trigger=trigger,
                previous_trigger=previous_trigger))
        previous_trigger = trigger

        if record['target'] > MAX_TARGET_NUMBER:
            report.add(finding(
                'roi_id_overflow', paths.bin_id, path=paths.adc,
                target=record['target']))


def _check_roi_ranges(paths, targets, roi_size, report) -> None:
    """Check that every target's byte range fits, and that the file is covered.

    This is the whole ADC↔ROI consistency group, and none of it needs the ROI
    bytes — the ADC offsets plus the .roi file size are enough.
    """
    previous = None
    for record in targets:
        offset = record['offset']
        needed = record['width'] * record['height']
        if offset >= roi_size:
            report.add(finding(
                'roi_offset_past_eof', paths.bin_id, path=paths.roi,
                target=record['target'], offset=offset, roi_size=roi_size))
        elif offset + needed > roi_size:
            report.add(finding(
                'roi_short_read', paths.bin_id, path=paths.roi,
                target=record['target'], needed=needed, offset=offset,
                available=roi_size - offset))

        if previous is not None:
            previous_offset, previous_end, previous_target = previous
            if offset < previous_offset:
                report.add(finding(
                    'roi_offsets_non_monotonic', paths.bin_id, path=paths.roi,
                    target=record['target'], offset=offset,
                    previous_target=previous_target,
                    previous_offset=previous_offset))
            elif offset < previous_end:
                report.add(finding(
                    'roi_overlapping_targets', paths.bin_id, path=paths.roi,
                    target=record['target'], offset=offset,
                    previous_target=previous_target,
                    overlap=previous_end - offset))
        previous = (offset, offset + needed, record['target'])

    covered = _covered_bytes(targets, roi_size)
    unaccounted = roi_size - covered
    if unaccounted > UNACCOUNTED_SLACK_BYTES:
        report.add(finding(
            'roi_unaccounted_bytes', paths.bin_id, path=paths.roi,
            unaccounted=unaccounted, roi_size=roi_size))


def _covered_bytes(targets, roi_size: int) -> int:
    """Return how many .roi bytes are claimed by at least one target."""
    ranges = sorted(
        (record['offset'],
         min(record['offset'] + record['width'] * record['height'], roi_size))
        for record in targets)
    covered = 0
    current_start = current_end = None
    for start, end in ranges:
        if end <= start:
            continue
        if current_end is None or start > current_end:
            if current_end is not None:
                covered += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        covered += current_end - current_start
    return covered


def _check_roi_decode(paths, targets, report) -> None:
    """Decode every ROI image — the only check that reads the .roi bytes."""
    try:
        with open(paths.roi, 'rb') as f:
            roi_bytes = f.read()
    except OSError as e:
        report.add(finding(
            'unreadable_file', paths.bin_id, path=paths.roi,
            ext='roi', error=str(e)))
        return

    for record in targets:
        try:
            image = roi_mod.extract_roi_images_from_targets([record], roi_bytes)
            image[record['target']].load()
        except Exception as e:  # PIL raises a variety of types here
            report.add(finding(
                'roi_decode_failure', paths.bin_id, path=paths.roi,
                target=record['target'], error=f'{type(e).__name__}: {e}'))


def _check_adc(paths, sizes, props, report, cost, enabled) -> list:
    """Run the ADC and ADC↔ROI groups.

    :returns: the parsed target records (empty if the ADC could not be read)
    """
    if sizes['adc'] is None:
        return []
    try:
        with open(paths.adc, 'rb') as f:
            adc_bytes = f.read()
    except OSError as e:
        report.add(finding(
            'unreadable_file', paths.bin_id, path=paths.adc,
            ext='adc', error=str(e)))
        return []

    n_lines = len(adc_bytes.decode('utf-8', errors='replace').splitlines())
    if n_lines == 0:
        report.add(finding('adc_empty', paths.bin_id, path=paths.adc))
        return []

    try:
        adc_bytes.decode('utf-8')
    except UnicodeDecodeError as e:
        report.add(finding(
            'adc_non_utf8', paths.bin_id, path=paths.adc,
            error=f'byte {e.start}: {e.reason}'))

    cols = adc_mod.columns_for_bin_id(paths.bin_id)
    diagnostics: list = []
    targets = list(adc_mod.iter_adc_targets(
        paths.bin_id, adc_bytes, diagnostics=diagnostics))

    _report_adc_diagnostics(paths, diagnostics, cols, report, enabled)
    _check_adc_layout(paths, diagnostics, cols, props, n_lines, report)
    _check_targets(paths, targets, report)

    if not targets:
        report.add(finding(
            'zero_rois', paths.bin_id, path=paths.adc, n_triggers=n_lines))
        return targets

    if sizes['roi']:
        _check_roi_ranges(paths, targets, sizes['roi'], report)
        if cost_allows(cost, Cost.FULL):
            _check_roi_decode(paths, targets, report)
    return targets


def _resolve_adcmod(paths: FilesetPaths, root_path, adcmod) -> str | None:
    """Return the .adc.mod path for this fileset, if one is in play.

    :param paths: the fileset paths
    :param root_path: raw data root, from which the sibling adcmod tree is
      derived by :func:`ifcbkit.fileset.adcmod_path`
    :param adcmod: an explicit .adc.mod path, overriding ``root_path``
    """
    if adcmod is not None:
        return str(adcmod)
    if root_path is None:
        return None
    return adcmod_path(paths.directory, paths.bin_id, root_path)


def _check_adcmod(paths, sizes, mod_path, raw_targets, report) -> list | None:
    """Compare a corrected ADC against the raw one.

    A correction that changes target count or geometry is not a defect — that
    is what corrections are for — so those are ``info``. What matters is a
    correction that cannot be used, or one with no raw fileset to correct.

    :returns: the corrected target records, or None if there is no usable
      correction. Consumers read the correction in place of the raw .adc (see
      :func:`ifcbkit.fileset.sync_resolve_adc_path`), so these — not the raw
      targets — are the bin's real target set for anything downstream.
    """
    if not os.path.exists(mod_path):
        return None

    if sizes['adc'] is None:
        report.add(finding(
            'adcmod_orphan', paths.bin_id, path=mod_path))
        return None

    try:
        with open(mod_path, 'rb') as f:
            mod_bytes = f.read()
    except OSError as e:
        report.add(finding(
            'adcmod_invalid', paths.bin_id, path=mod_path, reason=str(e)))
        return None

    mod_targets = list(adc_mod.iter_adc_targets(paths.bin_id, mod_bytes))
    if not mod_targets:
        report.add(finding(
            'adcmod_invalid', paths.bin_id, path=mod_path,
            reason='it contains no usable targets'))
        return None

    if len(mod_targets) != len(raw_targets):
        report.add(finding(
            'adcmod_row_delta', paths.bin_id, path=mod_path,
            mod_count=len(mod_targets), raw_count=len(raw_targets)))

    geometry = {'x', 'y', 'width', 'height', 'offset'}
    raw_by_target = {record['target']: record for record in raw_targets}
    changed = sum(
        1 for record in mod_targets
        if record['target'] in raw_by_target
        and any(record[key] != raw_by_target[record['target']][key]
                for key in geometry))
    if changed:
        report.add(finding(
            'adcmod_geometry_delta', paths.bin_id, path=mod_path,
            count=changed))
    return mod_targets


def check_fileset(path, *, bin_id=None, cost=Cost.PARSE,
                  root_path=None, adcmod=None, targets_out=None,
                  enable=(), roi_optional=False) -> Report:
    """Check one raw fileset for integrity.

    :param path: basepath, a .hdr/.adc/.roi path, or a bin-named directory
    :param bin_id: the bin ID, if it differs from the basename
    :param cost: I/O budget; see :class:`ifcbkit.qc.Cost`
    :param root_path: the raw data root, if corrected ADC files should be
      checked; the ``adcmod`` tree is its sibling
    :param adcmod: an explicit .adc.mod path, instead of deriving one
    :param enable: opt-in check codes to run, or ``'all'``; see
      :data:`ifcbkit.qc.registry.OPT_IN_CHECKS`. Ones left off are recorded in
      :attr:`Report.skipped`, never passed over in silence
    :param roi_optional: treat an absent .roi as expected instead of an error.
      ROI telemetry can lag the .hdr and .adc, so a dataset mid-transfer has
      bins that are incomplete on purpose. ``missing_roi`` then lands in
      :attr:`Report.skipped` rather than being emitted, because the ADC-to-ROI
      checks genuinely could not run
    :param targets_out: optional list; the bin's *effective* target records are
      appended to it, so a caller that also needs them (product coverage
      checks) does not have to parse the ADC a second time. Effective means
      the corrected ADC's targets when a usable correction is in play, because
      that is the ADC consumers read and the one products were derived from;
      the raw ADC's targets otherwise. The findings still report on the raw
      ADC either way — QC never silently prefers a correction.
    :returns: a :class:`Report` for this bin
    """
    cost = Cost(cost)
    enabled = resolve_opt_ins(enable)
    paths = resolve_fileset(path, bin_id)
    report = Report(subject=paths.bin_id, cost=cost)
    note_opt_in_skips(report, RAW_GROUPS, enabled)

    sizes = _sizes(paths, report, roi_optional)
    _check_sizes(paths, sizes, report)
    parsed_id = _check_identifiers(paths, report)
    mod_path = _resolve_adcmod(paths, root_path, adcmod)

    if cost_allows(cost, Cost.PARSE):
        props = _check_header(paths, parsed_id, report)
        targets = _check_adc(paths, sizes, props, report, cost, enabled)
        effective = targets
        if mod_path is not None:
            mod_targets = _check_adcmod(
                paths, sizes, mod_path, targets, report)
            if mod_targets is not None:
                effective = mod_targets
        if targets_out is not None:
            targets_out.extend(effective)
    elif mod_path is not None and os.path.exists(mod_path) \
            and sizes['adc'] is None:
        report.add(finding(
            'adcmod_orphan', paths.bin_id, path=mod_path))

    return report
