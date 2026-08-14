"""Tests for the unified ADC parse path (ifcbkit.adc.iter_adc_targets).

The ADC line-parsing logic used to exist in five places with three different
failure behaviors. These tests pin down the single behavior they were collapsed
onto, and guard against the duplication coming back.
"""

import asyncio
import os
import shutil

import pytest

from ifcbkit import adc as adc_mod
from ifcbkit.adc import (
    iter_adc_targets, parse_adc_bytes, parse_adc_line, I_STYLE_COLUMNS,
)
from ifcbkit.fileset import SyncIfcbDataDirectory, AsyncIfcbDataDirectory
from ifcbkit.roi import extract_roi_images
from ifcbkit.stitching import bin_images
from ifcbkit.stores.filesystem import AsyncFilesystemBinStore

from tests.conftest import DATA_DIR, D_BIN_ID, I_BIN_ID

I_FIXTURE_DIR = os.path.join(DATA_DIR, I_BIN_ID)


def _fixture_bytes(bin_id, ext):
    with open(os.path.join(DATA_DIR, bin_id, f'{bin_id}.{ext}'), 'rb') as f:
        return f.read()


def _damaged_fileset(tmp_path, damage):
    """Copy the I-style fixture into tmp_path, applying `damage` to the ADC.

    :param damage: callable taking the raw .adc bytes and returning new bytes
    :returns: (root_path, bin_id)
    """
    root = tmp_path / 'data'
    day_dir = root / I_BIN_ID
    os.makedirs(day_dir, exist_ok=True)
    for ext in ('hdr', 'roi'):
        shutil.copy(
            os.path.join(I_FIXTURE_DIR, f'{I_BIN_ID}.{ext}'),
            os.path.join(day_dir, f'{I_BIN_ID}.{ext}'),
        )
    with open(os.path.join(day_dir, f'{I_BIN_ID}.adc'), 'wb') as f:
        f.write(damage(_fixture_bytes(I_BIN_ID, 'adc')))
    return str(root), I_BIN_ID


def _corrupt_second_line(adc_bytes):
    lines = adc_bytes.split(b'\n')
    lines[1] = b'this,is,not,a,valid,adc,line'
    return b'\n'.join(lines)


def _non_utf8(adc_bytes):
    return adc_bytes.replace(b'\n', b'\n\xff\xfe,garbage\n', 1)


# --- list_images no longer raises on a malformed line ---

class TestListImagesSkipsMalformed:
    """Previously the directory classes raised while the stores skipped."""

    def test_sync_list_images_skips(self, tmp_path):
        root, pid = _damaged_fileset(tmp_path, _corrupt_second_line)
        images = SyncIfcbDataDirectory(root).list_images(pid)
        assert 2 not in images
        assert images  # the rest of the bin still parses

    def test_async_list_images_skips(self, tmp_path):
        root, pid = _damaged_fileset(tmp_path, _corrupt_second_line)
        images = asyncio.run(AsyncIfcbDataDirectory(root).list_images(pid))
        assert 2 not in images
        assert images

    def test_directory_and_store_agree(self, tmp_path):
        """SyncIfcbDataDirectory, AsyncIfcbDataDirectory and AsyncBinStore
        all named this operation list_images but disagreed on damaged data."""
        root, pid = _damaged_fileset(tmp_path, _corrupt_second_line)

        sync_images = SyncIfcbDataDirectory(root).list_images(pid)
        async_images = asyncio.run(AsyncIfcbDataDirectory(root).list_images(pid))
        store_images = asyncio.run(
            AsyncFilesystemBinStore(root).list_images(pid))

        assert sync_images == async_images == store_images

    def test_non_utf8_adc_does_not_raise(self, tmp_path):
        """The directory classes used to read the ADC in the platform's
        default text encoding."""
        root, pid = _damaged_fileset(tmp_path, _non_utf8)
        images = SyncIfcbDataDirectory(root).list_images(pid)
        assert images


# --- ADC parsing and ROI extraction agree on the target set ---

class TestAdcRoiAgreement:
    """ifcb-ingest zips parse_adc_bytes() against extract_roi_images()."""

    @pytest.mark.parametrize('bin_id', [D_BIN_ID, I_BIN_ID])
    def test_agree_on_intact_bin(self, bin_id):
        adc_bytes = _fixture_bytes(bin_id, 'adc')
        roi_bytes = _fixture_bytes(bin_id, 'roi')
        assert (set(parse_adc_bytes(bin_id, adc_bytes)) ==
                set(extract_roi_images(bin_id, adc_bytes, roi_bytes)))

    def test_agree_on_damaged_bin(self):
        adc_bytes = _corrupt_second_line(_fixture_bytes(I_BIN_ID, 'adc'))
        roi_bytes = _fixture_bytes(I_BIN_ID, 'roi')
        plain = set(parse_adc_bytes(I_BIN_ID, adc_bytes))
        extended = set(parse_adc_bytes(I_BIN_ID, adc_bytes, extended=True))
        images = set(extract_roi_images(I_BIN_ID, adc_bytes, roi_bytes))
        assert plain == extended == images
        assert 2 not in plain


# --- An unusable offset column disqualifies the target everywhere ---

class TestOffsetRequired:
    """parse_adc_bytes(extended=True) used to emit an entry with no 'offset'
    key when that column failed to parse; extract_roi_images dropped it."""

    @staticmethod
    def _line_with_bad_offset():
        text = _fixture_bytes(I_BIN_ID, 'adc').decode()
        fields = text.splitlines()[0].split(',')
        fields[I_STYLE_COLUMNS['offset']] = 'NaN'
        return ','.join(fields)

    def test_extended_skips_target(self):
        line = self._line_with_bad_offset()
        assert parse_adc_bytes(I_BIN_ID, line.encode(), extended=True) == {}

    def test_plain_skips_target(self):
        line = self._line_with_bad_offset()
        assert parse_adc_bytes(I_BIN_ID, line.encode()) == {}

    def test_parse_adc_line_skips_target(self):
        assert parse_adc_line(I_BIN_ID, self._line_with_bad_offset(), 0) is None

    def test_every_extended_entry_has_an_offset(self):
        adc = parse_adc_bytes(
            I_BIN_ID, _fixture_bytes(I_BIN_ID, 'adc'), extended=True)
        assert adc
        assert all('offset' in entry for entry in adc.values())


# --- The duplication must not come back ---

def test_roi_extraction_follows_the_adc_column_table(monkeypatch, tmp_path):
    """roi.py used to hardcode 11/12/13 and 15/16/17 of its own.

    Shifting the shared column table must move what ROI extraction reads; if
    roi.py reintroduces literals, this fails.
    """
    adc_bytes = _fixture_bytes(I_BIN_ID, 'adc')
    roi_bytes = _fixture_bytes(I_BIN_ID, 'roi')
    before = extract_roi_images(I_BIN_ID, adc_bytes, roi_bytes)

    # Swap width and height in the shared table.
    swapped = dict(I_STYLE_COLUMNS)
    swapped['width'], swapped['height'] = (
        I_STYLE_COLUMNS['height'], I_STYLE_COLUMNS['width'])
    monkeypatch.setattr(adc_mod, 'I_STYLE_COLUMNS', swapped)

    after = extract_roi_images(I_BIN_ID, adc_bytes, roi_bytes)
    assert after.keys() == before.keys()
    changed = [t for t in before
               if before[t].size != after[t].size]
    assert changed, 'roi.py did not follow the shared column table'


def test_bin_images_parses_the_adc_once(monkeypatch):
    """bin_images used to call parse_adc_bytes and then extract_roi_images,
    which parsed the same bytes a second time.

    Counts _columns_for_bin_id rather than iter_adc_targets: every ADC scan
    goes through it exactly once, whichever module holds the reference to
    iter_adc_targets.
    """
    calls = []
    real = adc_mod._columns_for_bin_id

    def counting(bin_id):
        calls.append(bin_id)
        return real(bin_id)

    monkeypatch.setattr(adc_mod, '_columns_for_bin_id', counting)

    bin_images(I_BIN_ID,
               _fixture_bytes(I_BIN_ID, 'adc'),
               _fixture_bytes(I_BIN_ID, 'roi'))
    assert calls == [I_BIN_ID]


def test_iter_adc_targets_records_are_complete():
    """Every public projection is a subset of these keys."""
    expected = {'target', 'roi_id', 'trigger', 'x', 'y', 'width', 'height',
                'offset'}
    records = list(iter_adc_targets(I_BIN_ID, _fixture_bytes(I_BIN_ID, 'adc')))
    assert records
    assert all(set(r) == expected for r in records)
