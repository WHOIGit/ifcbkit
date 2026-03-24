"""Tests for ifcbkit.adc — .adc file parsing."""

import pytest

from ifcbkit.adc import (
    parse_adc_bytes,
    parse_adc_file,
    parse_adc_line,
    _columns_for_bin_id,
    I_STYLE_COLUMNS,
    D_STYLE_COLUMNS,
)

from tests.conftest import D_BIN_ID, I_BIN_ID


# --- Column mapping ---

class TestColumnMapping:
    def test_i_style_columns(self):
        cols = _columns_for_bin_id('IFCB5_2012_028_081515')
        assert cols is I_STYLE_COLUMNS
        assert cols['x'] == 9
        assert cols['y'] == 10
        assert cols['width'] == 11
        assert cols['height'] == 12
        assert cols['offset'] == 13

    def test_d_style_columns(self):
        cols = _columns_for_bin_id('D20130526T095207_IFCB013')
        assert cols is D_STYLE_COLUMNS
        assert cols['x'] == 13
        assert cols['y'] == 14
        assert cols['width'] == 15
        assert cols['height'] == 16
        assert cols['offset'] == 17


# --- D-style ADC parsing (D20130526T095207_IFCB013) ---

class TestDStyleAdc:
    """Known values from pyifcb fileset_info: 19 ROIs, 118 targets."""

    def test_parse_adc_bytes_roi_count(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        assert len(adc) == 19

    def test_parse_adc_file_roi_count(self, d_adc_path):
        adc = parse_adc_file(D_BIN_ID, d_adc_path)
        assert len(adc) == 19

    def test_roi_numbers(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        expected = [7, 11, 13, 21, 32, 33, 47, 49, 54, 61, 66, 68, 73, 78, 80, 92, 99, 102, 114]
        assert sorted(adc.keys()) == expected

    def test_one_based_indexing(self, d_adc_bytes):
        """Target numbers are 1-based (line index + 1)."""
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        assert 0 not in adc
        assert min(adc.keys()) >= 1

    def test_roi_dimensions(self, d_adc_bytes):
        """ROI 99 should be 64 wide x 34 tall (from pyifcb fileset_info)."""
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        roi99 = adc[99]
        assert roi99['width'] == 64
        assert roi99['height'] == 34

    def test_roi_id_format(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        roi99 = adc[99]
        assert roi99['roi_id'] == 'D20130526T095207_IFCB013_00099'

    def test_all_rois_have_nonzero_dimensions(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        for target, data in adc.items():
            assert data['width'] > 0
            assert data['height'] > 0

    def test_extended_mode(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes, extended=True)
        roi = adc[7]  # first ROI
        assert 'trigger' in roi
        assert 'offset' in roi
        assert isinstance(roi['trigger'], int)
        assert isinstance(roi['offset'], int)

    def test_non_extended_omits_trigger_offset(self, d_adc_bytes):
        adc = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        roi = adc[7]
        assert 'trigger' not in roi
        assert 'offset' not in roi

    def test_file_matches_bytes(self, d_adc_path, d_adc_bytes):
        from_file = parse_adc_file(D_BIN_ID, d_adc_path)
        from_bytes = parse_adc_bytes(D_BIN_ID, d_adc_bytes)
        assert from_file == from_bytes


# --- I-style ADC parsing (IFCB5_2012_028_081515) ---

class TestIStyleAdc:
    """Known values from pyifcb fileset_info: 6 ROIs, 7 targets."""

    def test_parse_adc_bytes_roi_count(self, i_adc_bytes):
        adc = parse_adc_bytes(I_BIN_ID, i_adc_bytes)
        assert len(adc) == 6

    def test_roi_numbers(self, i_adc_bytes):
        adc = parse_adc_bytes(I_BIN_ID, i_adc_bytes)
        assert sorted(adc.keys()) == [1, 2, 3, 4, 5, 6]

    def test_roi_1_dimensions(self, i_adc_bytes):
        """ROI 1 should be 96 wide x 45 tall (from pyifcb fileset_info)."""
        adc = parse_adc_bytes(I_BIN_ID, i_adc_bytes)
        roi1 = adc[1]
        assert roi1['width'] == 96
        assert roi1['height'] == 45

    def test_roi_id_format(self, i_adc_bytes):
        adc = parse_adc_bytes(I_BIN_ID, i_adc_bytes)
        assert adc[1]['roi_id'] == 'IFCB5_2012_028_081515_00001'

    def test_extended_mode_trigger(self, i_adc_bytes):
        adc = parse_adc_bytes(I_BIN_ID, i_adc_bytes, extended=True)
        # First target's trigger number should be 1 (column 0 of first ADC line)
        assert adc[1]['trigger'] == 1

    def test_extended_mode_offset(self, i_adc_bytes):
        adc = parse_adc_bytes(I_BIN_ID, i_adc_bytes, extended=True)
        # First ROI starts at offset 1 in the .roi file
        assert adc[1]['offset'] == 1

    def test_file_matches_bytes(self, i_adc_path, i_adc_bytes):
        from_file = parse_adc_file(I_BIN_ID, i_adc_path)
        from_bytes = parse_adc_bytes(I_BIN_ID, i_adc_bytes)
        assert from_file == from_bytes

    def test_extended_file_matches_bytes(self, i_adc_path, i_adc_bytes):
        from_file = parse_adc_file(I_BIN_ID, i_adc_path, extended=True)
        from_bytes = parse_adc_bytes(I_BIN_ID, i_adc_bytes, extended=True)
        assert from_file == from_bytes


# --- parse_adc_line ---

class TestParseAdcLine:
    def test_i_style_line(self):
        line = '1,.3105469,.06072998046875,-.61004638671875,-.1776123046875,-3.6199951171875,-.29541015625,0,.2597656,202,673,96,45,1,-.27557373046875,'
        result = parse_adc_line(I_BIN_ID, line, 0)
        assert result is not None
        assert result['target'] == 1
        assert result['x'] == 202
        assert result['y'] == 673
        assert result['width'] == 96
        assert result['height'] == 45
        assert result['offset'] == 1
        assert result['roi_id'] == 'IFCB5_2012_028_081515_00001'

    def test_zero_dimension_returns_none(self):
        # D-style line with width=0, height=0 (no ROI)
        line = '1,0.047000,0.80304,0.02810,0.00149,0.01139,3.59266,0.26241,0.01078,0.01085,-999.00000,0.047000,0.094000,0,0,0,0,0,-999.000000,0,0,0,0.096671,0.000807'
        result = parse_adc_line(D_BIN_ID, line, 0)
        assert result is None

    def test_line_index_offset(self):
        line = '1,.3105469,.06072998046875,-.61004638671875,-.1776123046875,-3.6199951171875,-.29541015625,0,.2597656,202,673,96,45,1,-.27557373046875,'
        result = parse_adc_line(I_BIN_ID, line, 4)
        assert result['target'] == 5
        assert result['roi_id'] == 'IFCB5_2012_028_081515_00005'


# --- Edge cases ---

class TestAdcEdgeCases:
    def test_empty_bytes(self):
        adc = parse_adc_bytes(D_BIN_ID, b'')
        assert adc == {}

    def test_malformed_line_skipped(self):
        adc = parse_adc_bytes(D_BIN_ID, b'not,enough,fields\n')
        assert adc == {}

    def test_parse_adc_line_malformed(self):
        result = parse_adc_line(D_BIN_ID, 'bad', 0)
        assert result is None
