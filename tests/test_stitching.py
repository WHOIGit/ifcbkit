"""Tests for ifcbkit.stitching — pair detection, compositing, infill, BinImages."""

import pytest
from PIL import Image

from ifcbkit.adc import parse_adc_bytes
from ifcbkit.roi import extract_roi_images
from ifcbkit.stitching import (
    detect_pairs,
    stitch_pair,
    infill_stitched_image,
    BinImages,
    bin_images,
)

from tests.conftest import D_BIN_ID, I_BIN_ID


# Known-good values from pyifcb fileset_info.py
STITCHED_PAIR = (3, 4)
STITCHED_SHAPE = (263, 86)  # (width, height) in PIL convention
EXPECTED_KEYS = [1, 2, 3, 5, 6]
EXPECTED_CORNERS = {
    1: [208, 204, 205, 205],
    2: [205, 199, 203, 197],
    3: [210, 203, 207, 203],
    5: [210, 209, 212, 209],
    6: [212, 206, 209, 208],
}


def _corners(img):
    """Return [top-left, top-right, bottom-left, bottom-right] pixel values."""
    px = img.load()
    w, h = img.size
    return [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]


@pytest.fixture
def i_adc_extended(i_adc_bytes):
    return parse_adc_bytes(I_BIN_ID, i_adc_bytes, extended=True)


@pytest.fixture
def i_raw_images(i_adc_bytes, i_roi_bytes):
    return extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)


# --- detect_pairs ---

class TestDetectPairs:
    def test_i_style_finds_pair(self, i_adc_extended):
        pairs = detect_pairs(I_BIN_ID, i_adc_extended)
        assert pairs == [STITCHED_PAIR]

    def test_d_style_returns_empty(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes, extended=True)
        pairs = detect_pairs(D_BIN_ID, adc)
        assert pairs == []

    def test_no_pairs_without_matching_trigger(self):
        adc = {
            1: {'x': 0, 'y': 0, 'width': 50, 'height': 50, 'trigger': 1},
            2: {'x': 10, 'y': 10, 'width': 50, 'height': 50, 'trigger': 2},
        }
        assert detect_pairs('IFCB1_2000_001_000000', adc) == []

    def test_no_pairs_without_overlap(self):
        adc = {
            1: {'x': 0, 'y': 0, 'width': 50, 'height': 50, 'trigger': 1},
            2: {'x': 200, 'y': 200, 'width': 50, 'height': 50, 'trigger': 1},
        }
        assert detect_pairs('IFCB1_2000_001_000000', adc) == []

    def test_pair_with_matching_trigger_and_overlap(self):
        adc = {
            1: {'x': 0, 'y': 0, 'width': 50, 'height': 50, 'trigger': 1},
            2: {'x': 30, 'y': 10, 'width': 50, 'height': 50, 'trigger': 1},
        }
        assert detect_pairs('IFCB1_2000_001_000000', adc) == [(1, 2)]

    def test_empty_adc(self):
        assert detect_pairs('IFCB1_2000_001_000000', {}) == []


# --- stitch_pair ---

class TestStitchPair:
    def test_stitched_dimensions(self, i_adc_extended, i_raw_images):
        ta, tb = STITCHED_PAIR
        composite, mask = stitch_pair(
            i_adc_extended[ta], i_adc_extended[tb],
            i_raw_images[ta], i_raw_images[tb],
        )
        assert composite.size == STITCHED_SHAPE
        assert mask.size == STITCHED_SHAPE

    def test_composite_mode(self, i_adc_extended, i_raw_images):
        ta, tb = STITCHED_PAIR
        composite, mask = stitch_pair(
            i_adc_extended[ta], i_adc_extended[tb],
            i_raw_images[ta], i_raw_images[tb],
        )
        assert composite.mode == 'L'
        assert mask.mode == '1'

    def test_mask_has_gap_pixels(self, i_adc_extended, i_raw_images):
        ta, tb = STITCHED_PAIR
        _, mask = stitch_pair(
            i_adc_extended[ta], i_adc_extended[tb],
            i_raw_images[ta], i_raw_images[tb],
        )
        # Gap region should exist (bounding box is non-None)
        assert mask.getbbox() is not None

    def test_synthetic_pair(self):
        """Two overlapping 10x10 images with a known gap."""
        adc_a = {'x': 0, 'y': 0, 'width': 10, 'height': 10}
        adc_b = {'x': 5, 'y': 3, 'width': 10, 'height': 10}
        img_a = Image.new('L', (10, 10), 100)
        img_b = Image.new('L', (10, 10), 200)
        composite, mask = stitch_pair(adc_a, adc_b, img_a, img_b)
        # Stitched box: (0,0) to (15,13)
        assert composite.size == (15, 13)
        px = composite.load()
        mpx = mask.load()
        # Top-left corner: covered by img_a only
        assert px[0, 0] == 100
        assert mpx[0, 0] == 0
        # Overlap region: overwritten by img_b
        assert px[7, 5] == 200
        assert mpx[7, 5] == 0
        # Gap: top-right corner not covered by either
        assert px[14, 0] == 0
        assert mpx[14, 0] == 1


# --- infill_stitched_image ---

class TestInfill:
    def test_infill_fills_gap(self):
        """Infill should replace gap pixels with boundary mean."""
        # 5x5 image with a 1-pixel gap in the center
        img = Image.new('L', (5, 5), 200)
        mask = Image.new('1', (5, 5), 0)
        mask.putpixel((2, 2), 1)
        img.putpixel((2, 2), 0)  # gap pixel

        infilled = infill_stitched_image(img, mask)
        # Boundary mean: all 4 neighbors are 200
        assert infilled.load()[2, 2] == 200

    def test_infill_no_gap(self):
        """No gap → returns copy unchanged."""
        img = Image.new('L', (5, 5), 128)
        mask = Image.new('1', (5, 5), 0)
        infilled = infill_stitched_image(img, mask)
        assert list(infilled.tobytes()) == list(img.tobytes())

    def test_real_infill_corners(self, i_adc_extended, i_raw_images):
        """Infilled stitched ROI 3 corners match pyifcb."""
        ta, tb = STITCHED_PAIR
        composite, mask = stitch_pair(
            i_adc_extended[ta], i_adc_extended[tb],
            i_raw_images[ta], i_raw_images[tb],
        )
        infilled = infill_stitched_image(composite, mask)
        assert _corners(infilled) == EXPECTED_CORNERS[3]


# --- BinImages ---

class TestBinImages:
    def test_keys(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        assert list(bi.keys()) == EXPECTED_KEYS

    def test_len(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        assert len(bi) == 5

    def test_pairs(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        assert bi.pairs == [STITCHED_PAIR]

    def test_excluded_target_raises(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        with pytest.raises(KeyError):
            bi[4]

    def test_excluded_target_not_in(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        assert 4 not in bi

    def test_stitched_target_dimensions(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        assert bi[3].size == STITCHED_SHAPE

    def test_all_corner_values(self, i_adc_extended, i_raw_images):
        """All infilled corner values match pyifcb known-good values."""
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        for target in bi:
            assert _corners(bi[target]) == EXPECTED_CORNERS[target], \
                f'Corner mismatch for target {target}'

    def test_get_raw_stitched(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        composite, mask = bi.get_raw(3)
        assert composite.size == STITCHED_SHAPE
        assert mask is not None
        assert mask.mode == '1'

    def test_get_raw_non_stitched(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        img, mask = bi.get_raw(1)
        assert mask is None

    def test_stitch_false(self, i_adc_extended, i_raw_images):
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images, stitch=False)
        assert bi.pairs == []
        assert list(bi.keys()) == [1, 2, 3, 4, 5, 6]
        assert len(bi) == 6

    def test_mapping_protocol(self, i_adc_extended, i_raw_images):
        """BinImages is a Mapping — get, values, items work."""
        from collections.abc import Mapping
        bi = BinImages(I_BIN_ID, i_adc_extended, i_raw_images)
        assert isinstance(bi, Mapping)
        assert bi.get(1) is not None
        assert bi.get(4) is None  # excluded
        assert bi.get(9999) is None
        assert len(list(bi.values())) == 5
        assert len(list(bi.items())) == 5

    def test_d_style_passthrough(self, d_adc_bytes, d_roi_bytes):
        """D-style bins have no pairs — BinImages passes through unchanged."""
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes, extended=True)
        raw = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        bi = BinImages(D_BIN_ID, adc, raw)
        assert bi.pairs == []
        assert len(bi) == len(raw)
        assert list(bi.keys()) == sorted(raw.keys())


# --- bin_images factory ---

class TestBinImagesFactory:
    def test_i_style(self, i_adc_bytes, i_roi_bytes):
        bi = bin_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        assert isinstance(bi, BinImages)
        assert list(bi.keys()) == EXPECTED_KEYS
        assert bi.pairs == [STITCHED_PAIR]

    def test_d_style(self, d_adc_bytes, d_roi_bytes):
        bi = bin_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        assert isinstance(bi, BinImages)
        assert bi.pairs == []
        assert len(bi) == 19

    def test_stitch_false(self, i_adc_bytes, i_roi_bytes):
        bi = bin_images(I_BIN_ID, i_adc_bytes, i_roi_bytes, stitch=False)
        assert bi.pairs == []
        assert len(bi) == 6

    def test_corner_values_match(self, i_adc_bytes, i_roi_bytes):
        bi = bin_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        for target in bi:
            assert _corners(bi[target]) == EXPECTED_CORNERS[target], \
                f'Corner mismatch for target {target}'
