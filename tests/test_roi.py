"""Tests for ifcbkit.roi — .roi binary file reading."""

import pytest
from PIL import Image

from ifcbkit.roi import extract_roi_images, extract_roi_image

from tests.conftest import D_BIN_ID, I_BIN_ID


# --- D-style ROI extraction (D20130526T095207_IFCB013) ---

class TestDStyleRoi:
    """Known values from pyifcb fileset_info: 19 ROIs."""

    def test_image_count(self, d_adc_bytes, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        assert len(images) == 19

    def test_image_keys_match_adc(self, d_adc_bytes, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        expected = [7, 11, 13, 21, 32, 33, 47, 49, 54, 61, 66, 68, 73, 78, 80, 92, 99, 102, 114]
        assert sorted(images.keys()) == expected

    def test_image_type(self, d_adc_bytes, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        assert isinstance(images[7], Image.Image)

    def test_image_mode(self, d_adc_bytes, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        assert images[7].mode == 'L'

    def test_roi_99_dimensions(self, d_adc_bytes, d_roi_bytes):
        """ROI 99: 64 wide x 34 tall."""
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        img = images[99]
        assert img.size == (64, 34)  # PIL size is (width, height)

    def test_roi_99_pixel_values(self, d_adc_bytes, d_roi_bytes):
        """Check top-left 5x5 pixel block against known values."""
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes)
        img = images[99]
        pixels = img.load()
        expected = [
            [172, 168, 172, 166, 171],
            [168, 170, 172, 171, 170],
            [167, 174, 171, 175, 168],
            [173, 171, 173, 170, 171],
            [176, 169, 176, 173, 172],
        ]
        for y in range(5):
            for x in range(5):
                assert pixels[x, y] == expected[y][x], \
                    f'Pixel mismatch at ({x}, {y}): got {pixels[x, y]}, expected {expected[y][x]}'

    def test_rois_filter(self, d_adc_bytes, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes, rois={99, 7})
        assert sorted(images.keys()) == [7, 99]

    def test_rois_filter_empty(self, d_adc_bytes, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, d_adc_bytes, d_roi_bytes, rois={9999})
        assert len(images) == 0


# --- I-style ROI extraction (IFCB5_2012_028_081515) ---

class TestIStyleRoi:
    """Known values from pyifcb fileset_info: 6 ROIs."""

    def test_image_count(self, i_adc_bytes, i_roi_bytes):
        images = extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        assert len(images) == 6

    def test_image_keys(self, i_adc_bytes, i_roi_bytes):
        images = extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        assert sorted(images.keys()) == [1, 2, 3, 4, 5, 6]

    def test_roi_1_dimensions(self, i_adc_bytes, i_roi_bytes):
        """ROI 1: 96 wide x 45 tall."""
        images = extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        assert images[1].size == (96, 45)

    def test_roi_1_pixel_values(self, i_adc_bytes, i_roi_bytes):
        """Check top-left 5x5 pixel block against known values."""
        images = extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        img = images[1]
        pixels = img.load()
        expected = [
            [208, 207, 206, 206, 207],
            [206, 206, 206, 207, 206],
            [206, 207, 205, 206, 208],
            [208, 208, 208, 208, 209],
            [206, 206, 205, 207, 207],
        ]
        for y in range(5):
            for x in range(5):
                assert pixels[x, y] == expected[y][x], \
                    f'Pixel mismatch at ({x}, {y}): got {pixels[x, y]}, expected {expected[y][x]}'

    def test_all_images_grayscale(self, i_adc_bytes, i_roi_bytes):
        images = extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes)
        for target, img in images.items():
            assert img.mode == 'L', f'Target {target} is not grayscale'


# --- extract_roi_image (single image) ---

class TestExtractRoiImage:
    def test_single_image_from_file(self, i_roi_path):
        """Extract single ROI using offset, width, height from ADC."""
        # ROI 1: offset=1, width=96, height=45
        with open(i_roi_path, 'rb') as f:
            img = extract_roi_image(f, width=96, height=45, offset=1)
        assert isinstance(img, Image.Image)
        assert img.size == (96, 45)
        assert img.mode == 'L'
        # Check first pixel matches bulk extraction
        assert img.load()[0, 0] == 208

    def test_single_image_matches_bulk(self, i_adc_bytes, i_roi_bytes, i_roi_path):
        """Single extraction should produce identical pixels to bulk."""
        bulk = extract_roi_images(I_BIN_ID, i_adc_bytes, i_roi_bytes, rois={1})
        with open(i_roi_path, 'rb') as f:
            single = extract_roi_image(f, width=96, height=45, offset=1)
        assert list(bulk[1].tobytes()) == list(single.tobytes())


# --- Edge cases ---

class TestRoiEdgeCases:
    def test_empty_adc(self, d_roi_bytes):
        images = extract_roi_images(D_BIN_ID, b'', d_roi_bytes)
        assert images == {}
