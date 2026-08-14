"""
The QC check registry: every check code, exactly once.

Findings are only ever constructed through :func:`finding`, which looks the
code up here. Emitting an unregistered code is therefore impossible, the CLI's
``--list-checks`` is free, and a test can assert that every registered check is
actually reachable.

Severity is a property of the check, not of the caller. A consumer that wants
different policy filters by code — it does not get to re-grade a check.
"""

from dataclasses import dataclass

from .model import Cost, Finding, Severity


PRESENCE = 'presence'
IDENTIFIERS = 'identifiers'
HEADER = 'header'
ADC = 'adc'
ROI = 'roi'
ADCMOD = 'adcmod'
PRODUCTS = 'products'
COLLECTION = 'collection'

GROUPS = (PRESENCE, IDENTIFIERS, HEADER, ADC, ROI, ADCMOD, PRODUCTS, COLLECTION)


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """What a check is, independent of any particular subject.

    :param code: the registry key
    :param severity: fixed severity for this check
    :param cost: the minimum I/O budget at which this check can run
    :param group: which catalogue group it belongs to
    :param summary: one line describing what the check reports
    :param template: message template, formatted with the finding's detail
      keys; falls back to ``summary`` when absent
    :param opt_in: if True, the check only runs when explicitly requested
    """

    code: str
    severity: Severity
    cost: Cost
    group: str
    summary: str
    template: str = ''
    opt_in: bool = False


def _spec(code, severity, cost, group, summary, template='', opt_in=False):
    return CheckSpec(
        code=code, severity=severity, cost=cost, group=group,
        summary=summary, template=template or summary, opt_in=opt_in)


_SPECS = [
    # --- Raw fileset: presence and size ---
    _spec('missing_hdr', Severity.ERROR, Cost.STAT, PRESENCE,
          'The .hdr file is absent.'),
    _spec('missing_adc', Severity.ERROR, Cost.STAT, PRESENCE,
          'The .adc file is absent.'),
    _spec('missing_roi', Severity.ERROR, Cost.STAT, PRESENCE,
          'The .roi file is absent.'),
    _spec('zero_byte_file', Severity.ERROR, Cost.STAT, PRESENCE,
          'A fileset file is zero bytes.',
          '{ext} file is zero bytes.'),
    _spec('tiny_fileset', Severity.ERROR, Cost.STAT, PRESENCE,
          'The fileset is too small to contain data.',
          'fileset totals {total_bytes} bytes, below the {min_bytes}-byte minimum.'),
    _spec('unreadable_file', Severity.ERROR, Cost.STAT, PRESENCE,
          'A fileset file could not be read.',
          '{ext} file could not be read: {error}'),
    _spec('empty_roi_sentinel', Severity.INFO, Cost.STAT, PRESENCE,
          'The .roi file is a 1-byte old-style empty sentinel.'),

    # --- Raw fileset: identifiers ---
    _spec('unparseable_bin_id', Severity.ERROR, Cost.STAT, IDENTIFIERS,
          'The bin ID does not parse as I-style or D-style.',
          'bin ID does not parse: {error}'),
    _spec('bin_id_out_of_range', Severity.ERROR, Cost.STAT, IDENTIFIERS,
          'A bin ID field is outside its valid range.',
          'bin ID field {field}={value} is out of range ({reason}).'),
    _spec('basename_mismatch', Severity.ERROR, Cost.STAT, IDENTIFIERS,
          'Fileset files do not share one basename.',
          'basename {basename} does not match the bin ID {bin_id}.'),
    _spec('roi_id_overflow', Severity.ERROR, Cost.PARSE, IDENTIFIERS,
          'A target number exceeds the 5-digit ROI ID suffix.',
          'target {target} needs more than 5 digits, so its ROI ID will not parse.'),
    _spec('implausible_timestamp', Severity.WARNING, Cost.STAT, IDENTIFIERS,
          'The bin timestamp is outside the plausible IFCB era.',
          'bin timestamp {timestamp} is outside {earliest}..now.'),

    # --- Raw fileset: header ---
    _spec('hdr_unrecognized_format', Severity.ERROR, Cost.PARSE, HEADER,
          'The header format is recognized but not parsed.',
          'header format is not parsed: {context}'),
    _spec('hdr_cast_failure', Severity.ERROR, Cost.PARSE, HEADER,
          'A header value could not be cast to its schema type.',
          'header value {key}={value!r} is not a valid {type_name}.'),
    _spec('hdr_column_count_mismatch', Severity.ERROR, Cost.PARSE, HEADER,
          'The header column row and value row have different lengths.',
          'header has {n_columns} columns but {n_values} values, '
          'so values are mis-assigned.'),
    _spec('hdr_pid_instrument_mismatch', Severity.ERROR, Cost.PARSE, HEADER,
          'The header instrument ID disagrees with the bin ID.',
          'header instrument {hdr_instrument} does not match bin ID '
          'instrument {pid_instrument}.'),
    _spec('hdr_truncated', Severity.ERROR, Cost.PARSE, HEADER,
          'The header ends before its format requires.',
          'header has only {n_lines} line(s); {format_name} needs more.'),
    _spec('hdr_missing_keys', Severity.WARNING, Cost.PARSE, HEADER,
          'Expected header keys are absent.',
          'header is missing {missing}.'),
    _spec('hdr_pid_time_mismatch', Severity.WARNING, Cost.PARSE, HEADER,
          'The header sample time disagrees with the bin ID timestamp.',
          'header time {hdr_time} differs from bin ID time {pid_time} '
          'by {delta_seconds}s.'),

    # --- Raw fileset: ADC ---
    _spec('adc_empty', Severity.ERROR, Cost.PARSE, ADC,
          'The .adc file has no lines.'),
    _spec('adc_column_count_mismatch', Severity.ERROR, Cost.PARSE, ADC,
          'An .adc line has too few columns for its layout.',
          'line {line} has {n_fields} fields; the {style}-style layout needs '
          'at least {required}.'),
    _spec('adc_style_misdetected', Severity.ERROR, Cost.PARSE, ADC,
          'The column layout chosen from the bin ID contradicts the data.',
          '{style}-style layout was chosen from the bin ID but the data has '
          '{n_fields} columns ({reason}).'),
    _spec('adc_unparseable_line', Severity.ERROR, Cost.PARSE, ADC,
          'An .adc line has a non-integer value in a required column.',
          'line {line} does not parse: {text!r}'),
    _spec('adc_blank_line', Severity.ERROR, Cost.PARSE, ADC,
          'A blank .adc line shifts every subsequent target number.',
          'line {line} is blank, so targets after it are shifted.'),
    _spec('adc_absurd_geometry', Severity.ERROR, Cost.PARSE, ADC,
          'An ROI geometry is impossible for the instrument.',
          'target {target} has geometry {width}x{height} at ({x},{y}), '
          'outside the plausible range ({reason}).'),
    _spec('adc_format_declaration_mismatch', Severity.WARNING, Cost.PARSE, ADC,
          'The header ADCFileFormat declaration disagrees with the layout used.',
          'header declares {field} at column {declared_index} but the '
          '{style}-style layout reads it from column {used_index}.'),
    _spec('adc_non_utf8', Severity.WARNING, Cost.PARSE, ADC,
          'The .adc file is not valid UTF-8.',
          '.adc is not valid UTF-8 ({error}); bytes were replaced.'),
    _spec('adc_target_discontinuity', Severity.WARNING, Cost.PARSE, ADC,
          'Trigger numbers decrease within the .adc file.',
          'trigger {trigger} at target {target} decreases from '
          '{previous_trigger}.'),
    _spec('adc_zero_geometry', Severity.INFO, Cost.PARSE, ADC,
          'A trigger recorded no ROI (zero width or height).',
          '{count} trigger(s) recorded no ROI.'),

    # --- ADC <-> ROI consistency ---
    _spec('roi_offset_past_eof', Severity.ERROR, Cost.PARSE, ROI,
          'An ROI offset is beyond the end of the .roi file.',
          'target {target} offset {offset} is past the {roi_size}-byte .roi file.'),
    _spec('roi_short_read', Severity.ERROR, Cost.PARSE, ROI,
          'An ROI extends past the end of the .roi file.',
          'target {target} needs {needed} bytes at offset {offset} but only '
          '{available} remain.'),
    _spec('roi_overlapping_targets', Severity.ERROR, Cost.PARSE, ROI,
          'Two ROIs claim overlapping byte ranges.',
          'target {target} at offset {offset} overlaps target {previous_target} '
          'by {overlap} bytes.'),
    _spec('roi_decode_failure', Severity.ERROR, Cost.FULL, ROI,
          'An ROI image could not be decoded.',
          'target {target} failed to decode: {error}'),
    _spec('roi_offsets_non_monotonic', Severity.WARNING, Cost.PARSE, ROI,
          'ROI offsets do not increase with target number.',
          'target {target} offset {offset} is below target {previous_target} '
          'offset {previous_offset}.'),
    _spec('roi_unaccounted_bytes', Severity.WARNING, Cost.PARSE, ROI,
          'The .roi file has bytes no target claims.',
          '{unaccounted} of {roi_size} .roi bytes are not claimed by any target.'),
    _spec('zero_rois', Severity.INFO, Cost.PARSE, ROI,
          'The bin contains no ROIs.',
          'bin has {n_triggers} trigger(s) and no ROIs.'),

    # --- adcmod (corrected ADC files) ---
    _spec('adcmod_invalid', Severity.ERROR, Cost.PARSE, ADCMOD,
          'The corrected .adc.mod file is unusable.',
          'corrected ADC is unusable: {reason}'),
    _spec('adcmod_orphan', Severity.WARNING, Cost.STAT, ADCMOD,
          'A .adc.mod file has no corresponding raw fileset.'),
    _spec('adcmod_row_delta', Severity.INFO, Cost.PARSE, ADCMOD,
          'The corrected ADC has a different number of targets.',
          'corrected ADC has {mod_count} target(s) vs {raw_count} raw.'),
    _spec('adcmod_geometry_delta', Severity.INFO, Cost.PARSE, ADCMOD,
          'The corrected ADC changes ROI geometry.',
          'corrected ADC changes geometry for {count} target(s).'),

    # --- Products ---
    _spec('product_missing', Severity.ERROR, Cost.STAT, PRODUCTS,
          'A product declared as expected is absent.',
          'expected {product} product is absent; searched {searched}.'),
    _spec('product_container_corrupt', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A product container could not be opened.',
          '{product} container could not be opened: {error}'),
    _spec('features_missing_header', Severity.ERROR, Cost.FULL, PRODUCTS,
          'The features CSV has no header row.'),
    _spec('features_missing_roi_column', Severity.ERROR, Cost.FULL, PRODUCTS,
          'The features CSV has no ROI number column.',
          'features CSV has no roi_number/roiNumber column; columns are {columns}.'),
    _spec('features_non_numeric', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A features value is not numeric.',
          'features row {row} column {column} value {value!r} is not numeric.'),
    _spec('features_duplicate_rois', Severity.ERROR, Cost.FULL, PRODUCTS,
          'The features CSV has more than one row for an ROI.',
          'features CSV has {count} duplicate ROI number(s), e.g. {example}.'),
    _spec('features_empty_roi_number', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A features row has no ROI number.',
          'features row {row} has no ROI number.'),
    _spec('features_roi_not_in_bin', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A features row refers to a target the bin does not have.',
          'features CSV has {count} ROI number(s) not in the bin, e.g. {example}.'),
    _spec('class_missing_dataset', Severity.ERROR, Cost.FULL, PRODUCTS,
          'The class scores file lacks a required dataset.',
          'class scores file has no {dataset} dataset.'),
    _spec('class_shape_mismatch', Severity.ERROR, Cost.FULL, PRODUCTS,
          'Class score dataset shapes disagree.',
          'class scores are {scores_shape} but there are {n_labels} label(s) '
          'and {n_rois} ROI number(s).'),
    _spec('class_bad_values', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A class score is NaN or infinite.',
          'class scores contain {count} NaN/infinite value(s), e.g. ROI {example}.'),
    _spec('blobs_bad_roi_id', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A blob archive member is not named for a valid ROI ID.',
          'blob member {member!r} is not a valid ROI ID.'),
    _spec('blobs_pid_mismatch', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A blob archive member belongs to a different bin.',
          'blob member {member!r} belongs to bin {member_bin}.'),
    _spec('blobs_png_decode_failure', Severity.ERROR, Cost.FULL, PRODUCTS,
          'A blob PNG could not be decoded.',
          'blob {roi_id} failed to decode: {error}'),
    _spec('blobs_duplicate_members', Severity.ERROR, Cost.FULL, PRODUCTS,
          'The blob archive has more than one member for an ROI.',
          'blob archive has {count} duplicate ROI ID(s), e.g. {example}.'),
    _spec('product_unexpected_version', Severity.WARNING, Cost.STAT, PRODUCTS,
          'A product file has a version this library does not know.',
          '{product} product version {version} is not a known version '
          '({known}).'),
    _spec('features_ragged_rows', Severity.WARNING, Cost.FULL, PRODUCTS,
          'A features row has a different field count from the header.',
          'features row {row} has {n_fields} fields; the header has {n_columns}.'),
    _spec('features_roi_coverage', Severity.WARNING, Cost.FULL, PRODUCTS,
          'The features CSV does not cover every ROI in the bin.',
          'features cover {covered} of {total} ROI(s).'),
    _spec('class_roi_mismatch', Severity.WARNING, Cost.FULL, PRODUCTS,
          'Class score ROI numbers do not match the bin.',
          'class scores cover {covered} of {total} ROI(s); {extra} are not '
          'in the bin.'),
    _spec('blobs_roi_coverage', Severity.WARNING, Cost.FULL, PRODUCTS,
          'The blob archive does not cover every ROI in the bin.',
          'blobs cover {covered} of {total} ROI(s).'),

    # --- Collection ---
    _spec('fileset_incomplete', Severity.ERROR, Cost.STAT, COLLECTION,
          'A bin has some but not all of .hdr/.adc/.roi.',
          '{bin_id} has {present} but is missing {missing}.'),
    _spec('duplicate_pid', Severity.ERROR, Cost.STAT, COLLECTION,
          'The same bin ID appears in more than one directory.',
          '{bin_id} appears in {count} directories: {directories}'),
    _spec('day_dir_mismatch', Severity.WARNING, Cost.STAT, COLLECTION,
          'A bin is not in the day directory its ID implies.',
          '{bin_id} is in {actual} but its ID implies {expected}.'),
    _spec('dropped_by_filter', Severity.WARNING, Cost.STAT, COLLECTION,
          'A fileset was silently dropped by a listing filter.',
          '{bin_id} was dropped by the {filter_name} filter.'),
    _spec('adcmod_orphans', Severity.WARNING, Cost.STAT, COLLECTION,
          'The adcmod tree has corrections with no raw fileset.',
          '{count} .adc.mod file(s) have no raw fileset, e.g. {example}.'),
    _spec('excluded_by_path_rules', Severity.INFO, Cost.STAT, COLLECTION,
          'A directory was skipped by the include/exclude rules.',
          '{path} was skipped by the {rule} rule.'),
    _spec('missing_days', Severity.INFO, Cost.STAT, COLLECTION,
          'The date range has days with no data.',
          '{count} day(s) between {first} and {last} have no bins.'),
    _spec('empty_day_dir', Severity.INFO, Cost.STAT, COLLECTION,
          'A day directory contains no filesets.',
          '{path} contains no filesets.'),
    _spec('stray_files', Severity.INFO, Cost.STAT, COLLECTION,
          'A data directory contains files that are not IFCB data.',
          '{count} file(s) in {path} are not IFCB raw data, e.g. {example}.'),
    _spec('mixed_instruments', Severity.INFO, Cost.STAT, COLLECTION,
          'One directory holds bins from more than one instrument.',
          '{path} holds bins from instruments {instruments}.',
          opt_in=True),
]

CHECKS: dict = {spec.code: spec for spec in _SPECS}


def spec_for(code: str) -> CheckSpec:
    """Return the :class:`CheckSpec` for ``code``.

    :raises KeyError: if the code is not registered — this is the mechanism
      that makes an unregistered finding impossible to emit.
    """
    try:
        return CHECKS[code]
    except KeyError:
        raise KeyError(f'unregistered QC check code: {code!r}') from None


def finding(code: str, subject: str, *, path: str | None = None, **detail) -> Finding:
    """Build a :class:`Finding` for ``code``, rendering its message template.

    :param code: a registered check code
    :param subject: the bin ID or path the finding is about
    :param path: the specific file, when applicable
    :param detail: template arguments, also retained as structured detail
    :returns: a Finding whose severity comes from the registry
    """
    spec = spec_for(code)
    # ``path`` is a field rather than detail, but messages may still name it.
    namespace = dict(detail)
    if path is not None:
        namespace.setdefault('path', path)
    return Finding(
        code=code,
        severity=spec.severity,
        subject=subject,
        message=spec.template.format(**namespace) if namespace else spec.summary,
        path=path,
        detail=detail,
    )


def codes_for_group(group: str) -> list:
    """Return the codes in one catalogue group, in registration order."""
    return [spec.code for spec in _SPECS if spec.group == group]
