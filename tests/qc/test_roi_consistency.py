"""ADC-group checks and the ADC↔ROI consistency group."""

import os

from ifcbkit.qc import Cost, Severity
from ifcbkit.qc.raw import check_fileset

from .fixtures import (
    D_BIN_ID,
    I_BIN_ID,
    copy_fileset,
    edit_adc_line,
    read_adc_lines,
    set_adc_column,
    set_hdr_key,
    target_line_numbers,
    write_adc_lines,
    write_synthetic_adc,
)

# The committed D bin: 118 ADC lines, 19 of which describe an ROI.
D_LINES = 118
D_TARGETS = 19


def codes(report):
    return report.counts_by_code()


def detail_for(report, code):
    return next(f for f in report.findings if f.code == code).detail


# --- ADC group ---

def test_zero_geometry_is_opt_in(tmp_path):
    """Nearly every real bin has ROI-less triggers, so this stays quiet.

    A default-on check that fires on every bin ever collected is noise that
    buries the findings that matter.
    """
    basepath = copy_fileset(tmp_path)
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'adc_zero_geometry' not in codes(report)
    # Quiet, but accounted for: unrequested is not the same as passed.
    assert 'adc_zero_geometry' in report.skipped


def test_zero_geometry_is_aggregated_info_when_enabled(tmp_path):
    basepath = copy_fileset(tmp_path)
    report = check_fileset(
        basepath, cost=Cost.PARSE, enable=('adc_zero_geometry',))
    zero = next(f for f in report.findings if f.code == 'adc_zero_geometry')
    assert zero.severity is Severity.INFO
    assert zero.detail['count'] == D_LINES - D_TARGETS
    assert 'adc_zero_geometry' not in report.skipped


def test_adc_empty(tmp_path):
    basepath = copy_fileset(tmp_path)
    with open(basepath + '.adc', 'w'):
        pass
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'adc_empty' in codes(report)
    assert 'zero_rois' not in codes(report)


def test_adc_blank_line(tmp_path):
    basepath = copy_fileset(tmp_path)
    lines = read_adc_lines(basepath)
    write_adc_lines(basepath, lines[:5] + [''] + lines[5:])
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert detail_for(report, 'adc_blank_line')['line'] == 6


def test_adc_unparseable_line(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_adc_column(basepath, 2, 'width', 'wide')
    report = check_fileset(basepath, cost=Cost.PARSE)
    unparseable = detail_for(report, 'adc_unparseable_line')
    assert unparseable['line'] == 2
    assert 'wide' in unparseable['text']


def test_adc_column_count_mismatch(tmp_path):
    basepath = copy_fileset(tmp_path)
    edit_adc_line(basepath, 3, lambda fields: fields[:6])
    report = check_fileset(basepath, cost=Cost.PARSE)
    mismatch = detail_for(report, 'adc_column_count_mismatch')
    assert (mismatch['line'], mismatch['n_fields']) == (3, 6)
    assert mismatch['required'] == 18
    assert mismatch['style'] == 'D'


def test_adc_non_utf8(tmp_path):
    basepath = copy_fileset(tmp_path)
    with open(basepath + '.adc', 'rb') as f:
        raw = f.read()
    with open(basepath + '.adc', 'wb') as f:
        f.write(raw.replace(b'0', b'\xff', 1))
    report = check_fileset(basepath, cost=Cost.PARSE)
    non_utf8 = next(f for f in report.findings if f.code == 'adc_non_utf8')
    assert non_utf8.severity is Severity.WARNING


def test_adc_absurd_geometry(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_adc_column(basepath, target_line_numbers(basepath)[0], 'width', 999999)
    report = check_fileset(basepath, cost=Cost.PARSE)
    absurd = detail_for(report, 'adc_absurd_geometry')
    assert absurd['width'] == 999999
    assert 'exceed' in absurd['reason']


def test_negative_geometry_is_absurd(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_adc_column(basepath, target_line_numbers(basepath)[0], 'x', -5)
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert detail_for(report, 'adc_absurd_geometry')['reason'] == 'negative geometry'


def test_adc_target_discontinuity(tmp_path):
    basepath = copy_fileset(tmp_path)
    lines = read_adc_lines(basepath)
    # The second ROI-bearing line keeps its geometry but its trigger goes
    # backwards. Zero-geometry lines are skipped, so mutating one proves
    # nothing.
    number = target_line_numbers(basepath)[1]
    fields = lines[number - 1].split(',')
    fields[0] = '0'
    lines[number - 1] = ','.join(fields)
    write_adc_lines(basepath, lines)
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'adc_target_discontinuity' in codes(report)


def test_shared_triggers_are_not_a_discontinuity(tmp_path):
    # I-style stitched pairs share a trigger; the committed I bin has one.
    basepath = copy_fileset(tmp_path, I_BIN_ID)
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'adc_target_discontinuity' not in codes(report)


def test_adc_style_misdetected(tmp_path):
    # I-style-width data under a D-style bin ID: every row is too short for
    # the D layout, and long enough for the I layout.
    basepath = copy_fileset(
        tmp_path, I_BIN_ID, new_bin_id='D20120128T081515_IFCB005')
    write_synthetic_adc(basepath, n_fields=14)
    report = check_fileset(basepath, cost=Cost.PARSE)
    misdetected = detail_for(report, 'adc_style_misdetected')
    assert misdetected['style'] == 'D'
    assert 'I-style layout fits' in misdetected['reason']


def test_adc_format_declaration_mismatch(tmp_path):
    basepath = copy_fileset(tmp_path)
    # Move ROIx one column later than where the D-style layout reads it.
    names = ['trigger#', 'ADC_time', 'PMTA', 'PMTB', 'PMTC', 'PMTD',
             'peakA', 'peakB', 'peakC', 'peakD', 'time of flight',
             'grabtimestart', 'grabtimeend', 'spare', 'ROIx', 'ROIy',
             'ROIwidth', 'ROIheight', 'start_byte']
    set_hdr_key(basepath, 'ADCFileFormat', ', '.join(names))
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert codes(report)['adc_format_declaration_mismatch'] == 5
    mismatch = detail_for(report, 'adc_format_declaration_mismatch')
    assert mismatch['declared_index'] == mismatch['used_index'] + 1


def test_unusable_declaration_is_skipped_not_reported(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'ADCFileFormat', 'trigger#, ADC_time')
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'adc_format_declaration_mismatch' not in codes(report)
    assert 'adc_format_declaration_mismatch' in report.skipped


def test_roi_id_overflow(tmp_path):
    basepath = copy_fileset(tmp_path)
    template = read_adc_lines(basepath)[0].split(',')

    def line(trigger, width, height, offset):
        fields = list(template)
        fields[0] = str(trigger)
        fields[13], fields[14] = '10', '20'
        fields[15], fields[16], fields[17] = str(width), str(height), str(offset)
        return ','.join(fields)

    # Only the last of 100_001 triggers has an ROI, so its target number
    # needs six digits — more than the ROI ID suffix can hold.
    lines = [line(i + 1, 0, 0, 0) for i in range(100_000)]
    lines.append(line(100_001, 4, 4, 0))
    write_adc_lines(basepath, lines)
    with open(basepath + '.roi', 'wb') as f:
        f.write(b'\x00' * 16)

    report = check_fileset(basepath, cost=Cost.PARSE)
    assert detail_for(report, 'roi_id_overflow')['target'] == 100_001


# --- ADC <-> ROI consistency ---

def test_zero_rois_is_info(tmp_path):
    basepath = copy_fileset(tmp_path)
    lines = read_adc_lines(basepath)
    for number in range(1, len(lines) + 1):
        set_adc_column(basepath, number, 'width', 0)
    report = check_fileset(basepath, cost=Cost.PARSE)
    zero = next(f for f in report.findings if f.code == 'zero_rois')
    assert zero.severity is Severity.INFO
    assert zero.detail['n_triggers'] == D_LINES
    # No ROI-range checks are possible or attempted with no targets.
    assert 'roi_unaccounted_bytes' not in codes(report)


def test_roi_offset_past_eof(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_adc_column(
        basepath, target_line_numbers(basepath)[0], 'offset', 10_000_000)
    report = check_fileset(basepath, cost=Cost.PARSE)
    past = detail_for(report, 'roi_offset_past_eof')
    assert past['offset'] == 10_000_000
    assert past['roi_size'] == os.path.getsize(basepath + '.roi')


def test_roi_short_read(tmp_path):
    basepath = copy_fileset(tmp_path)
    roi_size = os.path.getsize(basepath + '.roi')
    lines = read_adc_lines(basepath)
    last = max(i for i, line in enumerate(lines, start=1)
               if int(line.split(',')[15]) > 0)
    set_adc_column(basepath, last, 'offset', roi_size - 4)
    report = check_fileset(basepath, cost=Cost.PARSE)
    short = detail_for(report, 'roi_short_read')
    assert short['available'] == 4
    assert short['needed'] > 4


def test_roi_overlapping_targets(tmp_path):
    basepath = copy_fileset(tmp_path)
    lines = read_adc_lines(basepath)
    targets = [i for i, line in enumerate(lines, start=1)
               if int(line.split(',')[15]) > 0]
    first_offset = int(lines[targets[0] - 1].split(',')[17])
    set_adc_column(basepath, targets[1], 'offset', first_offset + 1)
    report = check_fileset(basepath, cost=Cost.PARSE)
    overlap = detail_for(report, 'roi_overlapping_targets')
    assert overlap['overlap'] > 0
    assert overlap['previous_target'] == targets[0]


def test_roi_offsets_non_monotonic(tmp_path):
    basepath = copy_fileset(tmp_path)
    lines = read_adc_lines(basepath)
    targets = [i for i, line in enumerate(lines, start=1)
               if int(line.split(',')[15]) > 0]
    set_adc_column(basepath, targets[2], 'offset', 0)
    report = check_fileset(basepath, cost=Cost.PARSE)
    non_monotonic = detail_for(report, 'roi_offsets_non_monotonic')
    assert non_monotonic['offset'] == 0
    assert non_monotonic['target'] == targets[2]


def test_roi_unaccounted_bytes(tmp_path):
    basepath = copy_fileset(tmp_path)
    with open(basepath + '.roi', 'ab') as f:
        f.write(b'\x00' * 4096)
    report = check_fileset(basepath, cost=Cost.PARSE)
    unaccounted = detail_for(report, 'roi_unaccounted_bytes')
    assert unaccounted['unaccounted'] == 4096


def test_small_slack_is_not_reported_as_unaccounted(tmp_path):
    # I-style .roi files always leave a couple of bytes unclaimed.
    basepath = copy_fileset(tmp_path, I_BIN_ID)
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'roi_unaccounted_bytes' not in codes(report)


def test_roi_decode_failure_at_full_cost(tmp_path):
    basepath = copy_fileset(tmp_path)
    with open(basepath + '.roi', 'r+b') as f:
        f.truncate(64)
    parse_report = check_fileset(basepath, cost=Cost.PARSE)
    full_report = check_fileset(basepath, cost=Cost.FULL)
    assert 'roi_decode_failure' not in codes(parse_report)
    assert 'roi_decode_failure' in codes(full_report)
    # The cheap check already saw the problem; FULL confirms it in the decoder.
    assert 'roi_short_read' in codes(parse_report)
