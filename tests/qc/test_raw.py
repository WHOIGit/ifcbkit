"""Presence, size, identifier, and header checks on raw filesets."""

import os

from ifcbkit.qc import Cost, Severity
from ifcbkit.qc.raw import check_fileset, resolve_fileset

from .fixtures import (
    D_BIN_ID,
    I_BIN_ID,
    copy_fileset,
    remove_file,
    set_hdr_key,
    truncate_file,
    write_hdr_lines,
)


def codes(report):
    return report.counts_by_code()


# --- path resolution ---

def test_resolve_accepts_basepath_file_and_directory(tmp_path):
    basepath = copy_fileset(tmp_path)
    expected = resolve_fileset(basepath)
    assert expected.bin_id == D_BIN_ID
    for reference in (basepath + '.adc', basepath + '.hdr', basepath + '.roi',
                      os.path.dirname(basepath)):
        assert resolve_fileset(reference) == expected


def test_explicit_bin_id_overrides_the_basename(tmp_path):
    basepath = copy_fileset(tmp_path)
    paths = resolve_fileset(basepath, bin_id=I_BIN_ID)
    assert paths.bin_id == I_BIN_ID


# --- clean data ---

def test_real_bins_are_clean_at_every_cost(tmp_path):
    for bin_id in (D_BIN_ID, I_BIN_ID):
        basepath = copy_fileset(tmp_path, bin_id)
        for cost in (Cost.STAT, Cost.PARSE, Cost.FULL):
            report = check_fileset(basepath, cost=cost)
            assert report.errors == [], (bin_id, cost, report.errors)
            assert report.warnings == [], (bin_id, cost, report.warnings)


# --- presence and size ---

def test_missing_files_are_reported_per_extension(tmp_path):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')
    report = check_fileset(basepath, cost=Cost.STAT)
    assert 'missing_roi' in codes(report)
    assert report.findings[0].severity is Severity.ERROR
    assert report.findings[0].path.endswith('.roi')


def test_zero_byte_file(tmp_path):
    basepath = copy_fileset(tmp_path)
    truncate_file(basepath, 'adc', 0)
    report = check_fileset(basepath, cost=Cost.STAT)
    assert 'zero_byte_file' in codes(report)


def test_tiny_fileset(tmp_path):
    basepath = copy_fileset(tmp_path)
    for ext in ('hdr', 'adc', 'roi'):
        truncate_file(basepath, ext, 4)
    report = check_fileset(basepath, cost=Cost.STAT)
    assert 'tiny_fileset' in codes(report)
    detail = next(f for f in report.findings if f.code == 'tiny_fileset').detail
    assert detail['total_bytes'] == 12


def test_tiny_fileset_does_not_fire_when_nothing_is_present(tmp_path):
    report = check_fileset(str(tmp_path / 'nothing' / D_BIN_ID), cost=Cost.STAT)
    assert set(codes(report)) == {'missing_hdr', 'missing_adc', 'missing_roi'}


def test_empty_roi_sentinel_is_info(tmp_path):
    basepath = copy_fileset(tmp_path)
    truncate_file(basepath, 'roi', 1)
    report = check_fileset(basepath, cost=Cost.STAT)
    sentinel = next(f for f in report.findings if f.code == 'empty_roi_sentinel')
    assert sentinel.severity is Severity.INFO


def test_unreadable_file(tmp_path):
    basepath = copy_fileset(tmp_path)
    # A directory where a file belongs: stat succeeds, so this exercises the
    # read path rather than the stat path.
    os.remove(basepath + '.hdr')
    os.mkdir(basepath + '.hdr')
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'unreadable_file' in codes(report)


# --- identifiers ---

def test_unparseable_bin_id_stops_id_dependent_checks(tmp_path):
    basepath = copy_fileset(tmp_path, new_bin_id='not-a-bin-id')
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'unparseable_bin_id' in codes(report)
    assert 'implausible_timestamp' not in codes(report)
    assert 'hdr_pid_instrument_mismatch' not in codes(report)


def test_bin_id_out_of_range_day_of_year_zero(tmp_path):
    # bin_timestamp silently rolls DOY 0 into the previous year; QC does not.
    basepath = copy_fileset(tmp_path, I_BIN_ID, new_bin_id='IFCB5_2012_000_081515')
    report = check_fileset(basepath, cost=Cost.STAT)
    detail = next(
        f for f in report.findings if f.code == 'bin_id_out_of_range').detail
    assert detail['field'] == 'day_of_year'
    assert detail['value'] == 0


def test_bin_id_out_of_range_month_thirteen(tmp_path):
    basepath = copy_fileset(tmp_path, new_bin_id='D20131326T095207_IFCB013')
    report = check_fileset(basepath, cost=Cost.STAT)
    detail = next(
        f for f in report.findings if f.code == 'bin_id_out_of_range').detail
    assert (detail['field'], detail['value']) == ('month', 13)


def test_bin_id_out_of_range_day_of_year_366_in_a_common_year(tmp_path):
    basepath = copy_fileset(tmp_path, I_BIN_ID, new_bin_id='IFCB5_2013_366_081515')
    report = check_fileset(basepath, cost=Cost.STAT)
    assert 'bin_id_out_of_range' in codes(report)

    leap = copy_fileset(tmp_path, I_BIN_ID, new_bin_id='IFCB5_2012_366_081515')
    assert 'bin_id_out_of_range' not in codes(check_fileset(leap, cost=Cost.STAT))


def test_bin_id_out_of_range_hour(tmp_path):
    basepath = copy_fileset(tmp_path, new_bin_id='D20130526T995207_IFCB013')
    report = check_fileset(basepath, cost=Cost.STAT)
    detail = next(
        f for f in report.findings if f.code == 'bin_id_out_of_range').detail
    assert detail['field'] == 'hour'


def test_basename_mismatch(tmp_path):
    basepath = copy_fileset(tmp_path)
    report = check_fileset(basepath, bin_id=I_BIN_ID, cost=Cost.STAT)
    assert 'basename_mismatch' in codes(report)


def test_implausible_timestamp_is_a_warning(tmp_path):
    basepath = copy_fileset(tmp_path, new_bin_id='D19990526T095207_IFCB013')
    report = check_fileset(basepath, cost=Cost.STAT)
    stamp = next(f for f in report.findings if f.code == 'implausible_timestamp')
    assert stamp.severity is Severity.WARNING


def test_future_timestamp_is_implausible(tmp_path):
    basepath = copy_fileset(tmp_path, new_bin_id='D20990526T095207_IFCB013')
    assert 'implausible_timestamp' in codes(check_fileset(basepath, cost=Cost.STAT))


# --- header ---

def test_header_diagnostics_become_findings(tmp_path):
    basepath = copy_fileset(tmp_path)
    write_hdr_lines(basepath, [
        'Imaging FlowCytobot Acquisition Software version 2.0; May 2010'])
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'hdr_truncated' in codes(report)


def test_hdr_unrecognized_format(tmp_path):
    basepath = copy_fileset(tmp_path)
    write_hdr_lines(basepath, [
        'Imaging FlowCytobot Acquisition Software version 2.0; May 2010',
        'something that is not a Sample Date line',
        'more of the same',
    ])
    report = check_fileset(basepath, cost=Cost.PARSE)
    unrecognized = next(
        f for f in report.findings if f.code == 'hdr_unrecognized_format')
    assert unrecognized.severity is Severity.ERROR


def test_hdr_cast_failure(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'binarizeThreshold', 'eight')
    report = check_fileset(basepath, cost=Cost.PARSE)
    cast = next(f for f in report.findings if f.code == 'hdr_cast_failure')
    assert cast.detail['key'] == 'binarizeThreshold'
    assert 'eight' in cast.message


def test_hdr_pid_instrument_mismatch(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'imagerID', 99)
    report = check_fileset(basepath, cost=Cost.PARSE)
    mismatch = next(
        f for f in report.findings if f.code == 'hdr_pid_instrument_mismatch')
    assert mismatch.detail == {'hdr_instrument': 99, 'pid_instrument': 13}


def test_hdr_pid_time_mismatch(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'sampleTime', '2013-05-26T10:52:07Z')
    report = check_fileset(basepath, cost=Cost.PARSE)
    mismatch = next(
        f for f in report.findings if f.code == 'hdr_pid_time_mismatch')
    assert mismatch.severity is Severity.WARNING
    assert mismatch.detail['delta_seconds'] == 3600


def test_hdr_time_within_tolerance_is_not_reported(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'sampleTime', '2013-05-26T09:52:08Z')
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'hdr_pid_time_mismatch' not in codes(report)


def test_header_column_and_missing_key_findings(tmp_path):
    basepath = copy_fileset(tmp_path, I_BIN_ID)
    lines = [
        '"Imaging FlowCytobot Acquisition Software version 1.0; October 2005"',
        '"authors"', '"institution"', '"SyringeStatus =  0"',
        '"Temp Humidity BinarizeThresh PMT1hv(ssc) PMT2hv(chl) BlobSizeThresh"',
        '" 11.5"," 32.1"," 30"," .675"',
    ]
    write_hdr_lines(basepath, lines)
    report = check_fileset(basepath, cost=Cost.PARSE)
    assert 'hdr_column_count_mismatch' in codes(report)
    assert 'hdr_missing_keys' in codes(report)
    missing = next(f for f in report.findings if f.code == 'hdr_missing_keys')
    assert 'blobSizeThreshold' in missing.message


def test_header_is_not_read_at_stat_cost(tmp_path):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'imagerID', 99)
    report = check_fileset(basepath, cost=Cost.STAT)
    assert 'hdr_pid_instrument_mismatch' not in codes(report)
