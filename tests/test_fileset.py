"""Tests for fileset path resolution, including corrected (adcmod) ADC files."""

import asyncio
import os
import shutil
from datetime import datetime, timezone

import pytest

from ifcbkit.fileset import (
    SyncIfcbDataDirectory, AsyncIfcbDataDirectory, make_fileset_filter,
)

PID = 'D20170426T164105_IFCB009'
DAY = 'D20170426'

# Real I-style fixture (the actual adcmod use case). Its containing directory
# name is what the adcmod tree mirrors as the "day" subdirectory.
I_PID = 'IFCB5_2012_028_081515'
I_DAY = 'IFCB5_2012_028'
I_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'data', I_PID)


def _copy_i_fileset(day_dir):
    os.makedirs(day_dir, exist_ok=True)
    for ext in ('hdr', 'adc', 'roi'):
        shutil.copy(
            os.path.join(I_FIXTURE_DIR, f'{I_PID}.{ext}'),
            os.path.join(day_dir, f'{I_PID}.{ext}'),
        )


def _make_fileset(dirpath, pid):
    os.makedirs(dirpath, exist_ok=True)
    for ext in ('hdr', 'adc', 'roi'):
        with open(os.path.join(dirpath, f'{pid}.{ext}'), 'w') as f:
            f.write('')


def _make_adcmod(adcmod_root, day, pid, content='mod'):
    day_dir = os.path.join(adcmod_root, day)
    os.makedirs(day_dir, exist_ok=True)
    path = os.path.join(day_dir, f'{pid}.adc.mod')
    with open(path, 'w') as f:
        f.write(content)
    return path


def test_no_adcmod_uses_raw_adc(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(PID)['adc'] == str(root / DAY / f'{PID}.adc')


def test_adcmod_sibling_of_data_dir(tmp_path):
    # <root>/data/<day>/<pid>.adc  and  <root>/adcmod/<day>/<pid>.adc.mod
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(PID)['adc'] == mod


def test_adcmod_with_year_level(tmp_path):
    # <root>/data/2017/<day>/...  and  <root>/adcmod/<day>/<pid>.adc.mod
    root = tmp_path / 'data'
    _make_fileset(str(root / '2017' / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(PID)['adc'] == mod


def test_adcmod_appears_in_list(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root))
    entries = list(dd.list())
    assert len(entries) == 1
    assert entries[0]['adc'] == mod


def test_adcmod_inside_root_is_ignored(tmp_path):
    # adcmod is strictly a sibling of root_path; one nested inside root (here a
    # sibling of the intermediate year directory) must not be used.
    root = tmp_path / 'data'
    _make_fileset(str(root / '2017' / DAY), PID)
    _make_adcmod(str(root / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(PID)['adc'] == str(root / '2017' / DAY / f'{PID}.adc')


def test_adcmod_sibling_of_nonroot_ancestor_is_ignored(tmp_path):
    # <root> is <tmp>/raw/data, so only <tmp>/raw/adcmod counts -- an adcmod
    # sibling of <tmp>/raw's own parent must not be used.
    root = tmp_path / 'raw' / 'data'
    _make_fileset(str(root / DAY), PID)
    _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(PID)['adc'] == str(root / DAY / f'{PID}.adc')


def test_adcmod_sibling_of_root_with_trailing_slash(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root) + os.sep)
    assert dd.paths(PID)['adc'] == mod


def test_async_adcmod_resolution(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = AsyncIfcbDataDirectory(str(root))
    paths = asyncio.run(dd.paths(PID))
    assert paths['adc'] == mod


# --- I-style bins (the real adcmod use case) ---

def test_istyle_adcmod_path_resolves(tmp_path):
    root = tmp_path / 'data'
    _copy_i_fileset(str(root / I_DAY))
    # corrected ADC is a byte-identical copy of the raw ADC
    raw_adc = os.path.join(I_FIXTURE_DIR, f'{I_PID}.adc')
    mod = _make_adcmod(
        str(tmp_path / 'adcmod'), I_DAY, I_PID,
        content=open(raw_adc).read(),
    )
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(I_PID)['adc'] == mod


def test_istyle_read_images_through_adcmod(tmp_path):
    # End-to-end: I-style stitching must work reading the corrected ADC.
    root = tmp_path / 'data'
    _copy_i_fileset(str(root / I_DAY))
    raw_adc = os.path.join(I_FIXTURE_DIR, f'{I_PID}.adc')

    # baseline: raw ADC (no adcmod sibling)
    baseline = SyncIfcbDataDirectory(str(root)).read_images(I_PID)
    assert len(baseline) > 0

    # with a byte-identical corrected ADC present, results must match
    _make_adcmod(str(tmp_path / 'adcmod'), I_DAY, I_PID, content=open(raw_adc).read())
    dd = SyncIfcbDataDirectory(str(root))
    assert dd.paths(I_PID)['adc'].endswith('.adc.mod')
    corrected = dd.read_images(I_PID)
    assert set(corrected.keys()) == set(baseline.keys())
    for t in baseline:
        assert corrected[t].size == baseline[t].size


def test_istyle_corrected_adc_content_is_used(tmp_path):
    # Prove the corrected ADC (not the raw one) drives the output: zero out
    # one ROI's width in the .adc.mod so that target drops from the results.
    root = tmp_path / 'data'
    _copy_i_fileset(str(root / I_DAY))
    raw_adc = os.path.join(I_FIXTURE_DIR, f'{I_PID}.adc')

    baseline = SyncIfcbDataDirectory(str(root)).read_images(I_PID)
    dropped = sorted(baseline.keys())[0]

    # I-style: width at column 11, height at 12 (0-based)
    lines = open(raw_adc).read().splitlines()
    fields = lines[dropped - 1].split(',')
    fields[11] = '0'
    fields[12] = '0'
    lines[dropped - 1] = ','.join(fields)
    _make_adcmod(str(tmp_path / 'adcmod'), I_DAY, I_PID, content='\n'.join(lines) + '\n')

    corrected = SyncIfcbDataDirectory(str(root)).read_images(I_PID)
    assert dropped in baseline
    assert dropped not in corrected


# --- list() filtering: timestamp range / instrument ---

# Bins spanning two days, two instruments. Timestamps parsed from the PIDs.
BIN_A = 'D20200101T000000_IFCB100'  # 2020-01-01, instr 100
BIN_B = 'D20200102T120000_IFCB100'  # 2020-01-02, instr 100
BIN_C = 'D20200103T000000_IFCB200'  # 2020-01-03, instr 200


def _make_multi_bin_root(tmp_path):
    root = tmp_path / 'data'
    for pid in (BIN_A, BIN_B, BIN_C):
        _make_fileset(str(root / pid[:9]), pid)
    return root


def _pids(entries):
    return sorted(e['pid'] for e in entries)


def test_make_fileset_filter_none_when_no_args():
    assert make_fileset_filter() is None


def test_list_no_filter_returns_all(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    assert _pids(dd.list()) == [BIN_A, BIN_B, BIN_C]


def test_list_filter_by_instrument_int(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    assert _pids(dd.list(instrument=200)) == [BIN_C]


def test_list_filter_by_instrument_iterable(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    assert _pids(dd.list(instrument=[100, 200])) == [BIN_A, BIN_B, BIN_C]


def test_list_filter_by_instrument_str(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    assert _pids(dd.list(instrument='200')) == [BIN_C]


def test_list_filter_by_instrument_str_iterable(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    assert _pids(dd.list(instrument=['100', '200'])) == [BIN_A, BIN_B, BIN_C]


def test_make_fileset_filter_bad_instrument_raises():
    with pytest.raises(ValueError):
        make_fileset_filter(instrument='not-an-int')
    with pytest.raises(ValueError):
        make_fileset_filter(instrument=['100', 'bad'])
    with pytest.raises(ValueError):
        make_fileset_filter(instrument=True)


def test_list_filter_start_time_inclusive(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    start = datetime(2020, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert _pids(dd.list(start_time=start)) == [BIN_B, BIN_C]


def test_list_filter_end_time_exclusive(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    end = datetime(2020, 1, 3, 0, 0, 0, tzinfo=timezone.utc)
    assert _pids(dd.list(end_time=end)) == [BIN_A, BIN_B]


def test_list_filter_range_and_instrument(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = datetime(2020, 1, 3, tzinfo=timezone.utc)
    assert _pids(dd.list(start_time=start, end_time=end, instrument=100)) == [BIN_A, BIN_B]


def test_list_filter_naive_datetime_treated_utc(tmp_path):
    dd = SyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))
    start = datetime(2020, 1, 3)  # naive -> UTC
    assert _pids(dd.list(start_time=start)) == [BIN_C]


def test_async_list_filter(tmp_path):
    dd = AsyncIfcbDataDirectory(str(_make_multi_bin_root(tmp_path)))

    async def _collect():
        return [e async for e in dd.list(instrument=100)]

    assert _pids(asyncio.run(_collect())) == [BIN_A, BIN_B]
