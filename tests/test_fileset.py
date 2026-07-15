"""Tests for fileset path resolution, including corrected (adcmod) ADC files."""

import asyncio
import os
import shutil

import pytest

from ifcbkit.fileset import SyncIfcbDataDirectory, AsyncIfcbDataDirectory

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


def test_adcmod_boundary_not_walked_past_root(tmp_path):
    # adcmod as sibling of root_path itself is still resolved
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    dd = SyncIfcbDataDirectory(str(root))
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
