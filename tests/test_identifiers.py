"""Tests for ifcbkit.identifiers — bin ID and ROI ID parsing."""

from datetime import datetime, timezone

import pytest

from ifcbkit.identifiers import (
    parse_bin_id,
    parse_i_style_bin_id,
    parse_d_style_bin_id,
    parse_roi_id,
    parse_pid,
    add_target,
    bin_timestamp,
    bin_day_dir,
    bin_year,
    bin_instrument_id,
    parse_target,
)


# --- I-style bin IDs ---

class TestIStyleParsing:
    BIN_ID = 'IFCB5_2012_028_081515'

    def test_parse_i_style(self):
        result = parse_i_style_bin_id(self.BIN_ID)
        assert result['instrument_id'] == 5
        assert result['year'] == 2012
        assert result['day_of_year'] == 28
        assert result['hour'] == 8
        assert result['minute'] == 15
        assert result['second'] == 15

    def test_parse_bin_id_dispatches_to_i_style(self):
        result = parse_bin_id(self.BIN_ID)
        assert result['instrument_id'] == 5
        assert 'day_of_year' in result

    def test_timestamp(self):
        ts = bin_timestamp(self.BIN_ID)
        # Day 28 of 2012 = January 28
        assert ts == datetime(2012, 1, 28, 8, 15, 15, tzinfo=timezone.utc)

    def test_day_dir(self):
        assert bin_day_dir(self.BIN_ID) == 'IFCB5_2012_028'

    def test_year(self):
        assert bin_year(self.BIN_ID) == 2012

    def test_instrument_id(self):
        assert bin_instrument_id(self.BIN_ID) == 5

    def test_single_digit_instrument(self):
        result = parse_i_style_bin_id('IFCB1_2000_001_123456')
        assert result['instrument_id'] == 1

    def test_large_instrument_number(self):
        result = parse_i_style_bin_id('IFCB127_2020_365_235959')
        assert result['instrument_id'] == 127
        assert result['day_of_year'] == 365
        assert result['hour'] == 23
        assert result['minute'] == 59
        assert result['second'] == 59


# --- D-style bin IDs ---

class TestDStyleParsing:
    BIN_ID = 'D20130526T095207_IFCB013'

    def test_parse_d_style(self):
        result = parse_d_style_bin_id(self.BIN_ID)
        assert result['instrument_id'] == 13
        assert result['year'] == 2013
        assert result['month'] == 5
        assert result['day'] == 26
        assert result['hour'] == 9
        assert result['minute'] == 52
        assert result['second'] == 7

    def test_parse_bin_id_dispatches_to_d_style(self):
        result = parse_bin_id(self.BIN_ID)
        assert result['instrument_id'] == 13
        assert 'month' in result

    def test_timestamp(self):
        ts = bin_timestamp(self.BIN_ID)
        assert ts == datetime(2013, 5, 26, 9, 52, 7, tzinfo=timezone.utc)

    def test_day_dir(self):
        assert bin_day_dir(self.BIN_ID) == 'D20130526'

    def test_year(self):
        assert bin_year(self.BIN_ID) == 2013

    def test_instrument_id(self):
        assert bin_instrument_id(self.BIN_ID) == 13

    def test_three_digit_instrument(self):
        result = parse_d_style_bin_id('D20221227T093138_IFCB127')
        assert result['instrument_id'] == 127


# --- ROI IDs ---

class TestRoiIdParsing:
    def test_parse_d_style_roi_id(self):
        bin_id, target = parse_roi_id('D20130526T095207_IFCB013_00099')
        assert bin_id == 'D20130526T095207_IFCB013'
        assert target == 99

    def test_parse_i_style_roi_id(self):
        bin_id, target = parse_roi_id('IFCB5_2012_028_081515_00001')
        assert bin_id == 'IFCB5_2012_028_081515'
        assert target == 1

    def test_add_target(self):
        assert add_target('D20130526T095207_IFCB013', 99) == 'D20130526T095207_IFCB013_00099'
        assert add_target('IFCB5_2012_028_081515', 1) == 'IFCB5_2012_028_081515_00001'

    def test_add_target_zero_pads(self):
        assert add_target('D20130526T095207_IFCB013', 5) == 'D20130526T095207_IFCB013_00005'

    def test_roundtrip(self):
        bin_id = 'D20130526T095207_IFCB013'
        roi_id = add_target(bin_id, 42)
        parsed_bin, parsed_target = parse_roi_id(roi_id)
        assert parsed_bin == bin_id
        assert parsed_target == 42

    def test_parse_target_alias(self):
        """parse_target is a backward-compat alias for parse_roi_id."""
        assert parse_target is parse_roi_id


# --- parse_pid (unified parser) ---

class TestParsePid:
    def test_d_style_bin_id(self):
        result = parse_pid('D20130526T095207_IFCB013')
        assert result['lid'] == 'D20130526T095207_IFCB013'
        assert result['instrument_id'] == 13
        assert result['year'] == 2013
        assert result['day_dir'] == 'D20130526'
        assert isinstance(result['timestamp'], datetime)
        assert 'target' not in result

    def test_i_style_bin_id(self):
        result = parse_pid('IFCB5_2012_028_081515')
        assert result['lid'] == 'IFCB5_2012_028_081515'
        assert result['instrument_id'] == 5
        assert result['year'] == 2012

    def test_d_style_roi_id(self):
        result = parse_pid('D20130526T095207_IFCB013_00099')
        assert result['lid'] == 'D20130526T095207_IFCB013'
        assert result['target'] == 99
        assert result['roi_id'] == 'D20130526T095207_IFCB013_00099'

    def test_i_style_roi_id(self):
        result = parse_pid('IFCB5_2012_028_081515_00001')
        assert result['lid'] == 'IFCB5_2012_028_081515'
        assert result['target'] == 1


# --- Error cases ---

class TestInvalidIds:
    def test_empty_string(self):
        with pytest.raises(ValueError):
            parse_bin_id('')

    def test_garbage(self):
        with pytest.raises(ValueError):
            parse_bin_id('not_a_valid_id')

    def test_wrong_prefix(self):
        with pytest.raises(ValueError):
            parse_bin_id('X20130526T095207_IFCB013')

    def test_truncated_d_style(self):
        with pytest.raises(ValueError):
            parse_d_style_bin_id('D2013052')

    def test_truncated_i_style(self):
        with pytest.raises(ValueError):
            parse_i_style_bin_id('IFCB5_2012')

    def test_invalid_roi_id(self):
        with pytest.raises(ValueError):
            parse_roi_id('not_a_roi_id')

    def test_invalid_pid(self):
        with pytest.raises(ValueError):
            parse_pid('garbage')
