"""Tests for ifcbkit.header — .hdr file parsing."""

import pytest

from ifcbkit.header import parse_hdr, parse_hdr_file, parse_hdr_bytes


# --- D-style header (RFC 822 format, D20130526T095207_IFCB013) ---

class TestDStyleHeader:
    def test_parse_hdr_file(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert isinstance(hdr, dict)
        assert len(hdr) > 0

    def test_known_string_value(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert hdr['KloehnPort'] == 'COM3'

    def test_known_int_value(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert hdr['laserMotorSmallStep_ms'] == 1000
        assert isinstance(hdr['laserMotorSmallStep_ms'], int)

    def test_known_int_value_2(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert hdr['blobXgrowAmount'] == 20

    def test_context_present(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert 'context' in hdr

    def test_run_time(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert 'runTime' in hdr
        assert isinstance(hdr['runTime'], float)

    def test_temperature(self, d_hdr_path):
        hdr = parse_hdr_file(d_hdr_path)
        assert 'temperature' in hdr
        assert isinstance(hdr['temperature'], float)
        assert hdr['temperature'] == pytest.approx(35.270397)

    def test_parse_hdr_bytes_matches_file(self, d_hdr_path):
        hdr_file = parse_hdr_file(d_hdr_path)
        with open(d_hdr_path, 'rb') as f:
            hdr_bytes = parse_hdr_bytes(f.read())
        assert hdr_file == hdr_bytes


# --- I-style header (legacy metadata-column format, IFCB5_2012_028_081515) ---

class TestIStyleHeader:
    def test_parse_hdr_file(self, i_hdr_path):
        hdr = parse_hdr_file(i_hdr_path)
        assert isinstance(hdr, dict)
        assert len(hdr) > 0

    def test_known_int_value(self, i_hdr_path):
        hdr = parse_hdr_file(i_hdr_path)
        assert hdr['binarizeThreshold'] == 30
        assert isinstance(hdr['binarizeThreshold'], int)

    def test_known_float_value(self, i_hdr_path):
        hdr = parse_hdr_file(i_hdr_path)
        assert hdr['fluorescencePhotomultiplierSetting'] == pytest.approx(0.6)

    def test_temperature(self, i_hdr_path):
        hdr = parse_hdr_file(i_hdr_path)
        assert 'temperature' in hdr
        assert isinstance(hdr['temperature'], float)

    def test_humidity(self, i_hdr_path):
        hdr = parse_hdr_file(i_hdr_path)
        assert 'humidity' in hdr
        assert isinstance(hdr['humidity'], float)

    def test_context_present(self, i_hdr_path):
        hdr = parse_hdr_file(i_hdr_path)
        assert 'context' in hdr

    def test_parse_hdr_bytes_matches_file(self, i_hdr_path):
        hdr_file = parse_hdr_file(i_hdr_path)
        with open(i_hdr_path, 'rb') as f:
            hdr_bytes = parse_hdr_bytes(f.read())
        assert hdr_file == hdr_bytes


# --- Edge cases ---

class TestHeaderEdgeCases:
    def test_empty_lines(self):
        assert parse_hdr([]) == {}

    def test_parse_hdr_from_line_list(self):
        lines = [
            'softwareVersion: test v1.0\n',
            'key1: value1\n',
            'key2: 42\n',
        ]
        hdr = parse_hdr(lines)
        assert hdr['key1'] == 'value1'
        assert hdr['key2'] == 42
