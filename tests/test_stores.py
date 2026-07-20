"""Tests for filesystem-backed stores, including corrected (adcmod) ADC files."""

import asyncio
import os

from ifcbkit.stores.filesystem import AsyncFilesystemBinStore

PID = 'D20170426T164105_IFCB009'
DAY = 'D20170426'


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


def test_bin_store_no_adcmod_uses_raw_adc(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    store = AsyncFilesystemBinStore(str(root))
    path = asyncio.run(store.get_path(f'{PID}.adc'))
    assert path == str(root / DAY / f'{PID}.adc')


def test_bin_store_resolves_adcmod(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    store = AsyncFilesystemBinStore(str(root))
    assert asyncio.run(store.get_path(f'{PID}.adc')) == mod


def test_bin_store_get_reads_adcmod_content(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID, content='corrected')
    store = AsyncFilesystemBinStore(str(root))
    assert asyncio.run(store.get(f'{PID}.adc')) == b'corrected'


def test_bin_store_adcmod_does_not_affect_hdr_or_roi(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    store = AsyncFilesystemBinStore(str(root))
    assert asyncio.run(store.get_path(f'{PID}.hdr')) == str(root / DAY / f'{PID}.hdr')
    assert asyncio.run(store.get_path(f'{PID}.roi')) == str(root / DAY / f'{PID}.roi')


def test_bin_store_adcmod_with_year_level(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / '2017' / DAY), PID)
    mod = _make_adcmod(str(tmp_path / 'adcmod'), DAY, PID)
    store = AsyncFilesystemBinStore(str(root))
    assert asyncio.run(store.get_path(f'{PID}.adc')) == mod


def test_bin_store_exists_unknown_bin(tmp_path):
    root = tmp_path / 'data'
    _make_fileset(str(root / DAY), PID)
    store = AsyncFilesystemBinStore(str(root))
    assert asyncio.run(store.get_path('D20991231T000000_IFCB009.adc')) is None
