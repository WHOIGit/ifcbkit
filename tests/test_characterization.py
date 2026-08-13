"""Characterization tests pinning ADC/ROI output across the parse-path refactor.

These snapshot the exact output of every ADC-reading code path against the two
committed fixture bins. They were recorded before the five duplicated ADC parse
loops were collapsed onto ``iter_adc_targets``, and must keep passing unchanged
afterwards — they are the proof that well-formed data is unaffected.

To regenerate after an *intentional* change to well-formed-data behavior, run
this module as a script and paste the printed dict into ``SNAPSHOTS``.
"""

import asyncio
import hashlib
import json

import pytest

from ifcbkit.adc import parse_adc_bytes, parse_adc_file, parse_adc_line
from ifcbkit.fileset import SyncIfcbDataDirectory, AsyncIfcbDataDirectory
from ifcbkit.roi import extract_roi_images
from ifcbkit.stitching import bin_images

from tests.conftest import DATA_DIR, D_BIN_ID, I_BIN_ID


def _digest(obj) -> str:
    """Stable digest of a JSON-able structure."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()


def _image_repr(img):
    return [img.mode, list(img.size),
            hashlib.sha256(img.tobytes()).hexdigest()]


def _images_repr(images):
    return {str(t): _image_repr(img) for t, img in sorted(images.items())}


# --- The paths under characterization ---

def snapshot_adc_plain(bin_id, adc_bytes, roi_bytes, adc_path):
    return parse_adc_bytes(bin_id, adc_bytes)


def snapshot_adc_extended(bin_id, adc_bytes, roi_bytes, adc_path):
    return parse_adc_bytes(bin_id, adc_bytes, extended=True)


def snapshot_adc_file(bin_id, adc_bytes, roi_bytes, adc_path):
    return parse_adc_file(bin_id, adc_path, extended=True)


def snapshot_adc_lines(bin_id, adc_bytes, roi_bytes, adc_path):
    text = adc_bytes.decode('utf-8', errors='replace')
    return [parse_adc_line(bin_id, line, i)
            for i, line in enumerate(text.splitlines())]


def snapshot_roi_images(bin_id, adc_bytes, roi_bytes, adc_path):
    return _images_repr(extract_roi_images(bin_id, adc_bytes, roi_bytes))


def snapshot_roi_subset(bin_id, adc_bytes, roi_bytes, adc_path):
    # Every other target that actually has an ROI, so the `rois` filter is
    # exercised on both fixtures (the D bin has no ROI on targets 1-3).
    present = sorted(parse_adc_bytes(bin_id, adc_bytes))
    subset = set(present[::2])
    assert subset, 'fixture has no ROIs; subset test would be vacuous'
    return _images_repr(
        extract_roi_images(bin_id, adc_bytes, roi_bytes, rois=subset))


def snapshot_bin_images(bin_id, adc_bytes, roi_bytes, adc_path):
    bi = bin_images(bin_id, adc_bytes, roi_bytes)
    return {
        'pairs': [list(p) for p in bi.pairs],
        'targets': sorted(bi.keys()),
        'images': {str(t): _image_repr(bi[t]) for t in sorted(bi.keys())},
    }


def snapshot_list_images_sync(bin_id, adc_bytes, roi_bytes, adc_path):
    return SyncIfcbDataDirectory(DATA_DIR).list_images(bin_id)


def snapshot_list_images_async(bin_id, adc_bytes, roi_bytes, adc_path):
    return asyncio.run(AsyncIfcbDataDirectory(DATA_DIR).list_images(bin_id))


PATHS = {
    'adc_plain': snapshot_adc_plain,
    'adc_extended': snapshot_adc_extended,
    'adc_file': snapshot_adc_file,
    'adc_lines': snapshot_adc_lines,
    'roi_images': snapshot_roi_images,
    'roi_subset': snapshot_roi_subset,
    'bin_images': snapshot_bin_images,
    'list_images_sync': snapshot_list_images_sync,
    'list_images_async': snapshot_list_images_async,
}


# Recorded pre-refactor. Do not edit by hand.
SNAPSHOTS = {
    "D20130526T095207_IFCB013": {
        "adc_extended": "d9b63535448f7d53017da76b7b605355bfff7ee42678abbb1a6649da8f3681c4",
        "adc_file": "d9b63535448f7d53017da76b7b605355bfff7ee42678abbb1a6649da8f3681c4",
        "adc_lines": "cb2cb2f8f5d4b8b8645d5c12e976679b8b924b199f77221539a465f8d726c62f",
        "adc_plain": "0d3b4ae4658139cc82805521e841152628bb01d169cb352e6a5eb8ec6294887b",
        "bin_images": "a9037dd6f1c23a252cf8b9e7c5dc2faecef1896baa6c939d146407b1f36ec683",
        "list_images_async": "0d3b4ae4658139cc82805521e841152628bb01d169cb352e6a5eb8ec6294887b",
        "list_images_sync": "0d3b4ae4658139cc82805521e841152628bb01d169cb352e6a5eb8ec6294887b",
        "roi_images": "ecc2010ff25a85a45f73b90c2c1bc14af48c97882fe03d4f67c14db29a18dc23",
        "roi_subset": "205ffe191bb914f5517360fab0405a0c567adfae68d6d5b21a66c83d4199c7cb"
    },
    "IFCB5_2012_028_081515": {
        "adc_extended": "5f522eda180427d24436958a5c544a496e663e12d8569839fbcd5097d9e30c23",
        "adc_file": "5f522eda180427d24436958a5c544a496e663e12d8569839fbcd5097d9e30c23",
        "adc_lines": "d01b737510c78a84ee05c85050e8855acb3c81846ca53c9d85c4b5477ba1c94a",
        "adc_plain": "237c04550b4600859496ae920888995c771890c148855dcfcd564a4e8a815d69",
        "bin_images": "d7cd3479525024ff6f314cb59eb585eaaf0998032dbc2243d979e3d0a1476e9c",
        "list_images_async": "237c04550b4600859496ae920888995c771890c148855dcfcd564a4e8a815d69",
        "list_images_sync": "237c04550b4600859496ae920888995c771890c148855dcfcd564a4e8a815d69",
        "roi_images": "ce85944f6443913b69bc42dd2963b1c7f6c6b09d8f5a5f21ed4154b9b9a9ec3b",
        "roi_subset": "185d2c36af4bcc7ced14e782967631ad198439fdd1d469cf749b55097225bbdf"
    }
}


def _load(bin_id):
    import os
    base = os.path.join(DATA_DIR, bin_id, bin_id)
    with open(base + '.adc', 'rb') as f:
        adc_bytes = f.read()
    with open(base + '.roi', 'rb') as f:
        roi_bytes = f.read()
    return adc_bytes, roi_bytes, base + '.adc'


@pytest.mark.parametrize('bin_id', [D_BIN_ID, I_BIN_ID])
@pytest.mark.parametrize('path_name', sorted(PATHS))
def test_output_unchanged(bin_id, path_name):
    adc_bytes, roi_bytes, adc_path = _load(bin_id)
    result = PATHS[path_name](bin_id, adc_bytes, roi_bytes, adc_path)
    assert _digest(result) == SNAPSHOTS[bin_id][path_name], (
        f'{path_name} output changed for {bin_id}'
    )


if __name__ == '__main__':
    snaps = {}
    for bin_id in (D_BIN_ID, I_BIN_ID):
        adc_bytes, roi_bytes, adc_path = _load(bin_id)
        snaps[bin_id] = {
            name: _digest(fn(bin_id, adc_bytes, roi_bytes, adc_path))
            for name, fn in sorted(PATHS.items())
        }
    print(json.dumps(snaps, indent=4, sort_keys=True))
