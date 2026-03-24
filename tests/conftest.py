"""Shared fixtures for ifcbkit tests."""

import os

import pytest

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# D-style test bin
D_BIN_ID = 'D20130526T095207_IFCB013'
D_BIN_DIR = os.path.join(DATA_DIR, D_BIN_ID)

# I-style test bin
I_BIN_ID = 'IFCB5_2012_028_081515'
I_BIN_DIR = os.path.join(DATA_DIR, I_BIN_ID)


def _bin_path(bin_dir, bin_id, ext):
    return os.path.join(bin_dir, f'{bin_id}.{ext}')


@pytest.fixture
def d_hdr_path():
    return _bin_path(D_BIN_DIR, D_BIN_ID, 'hdr')


@pytest.fixture
def d_adc_path():
    return _bin_path(D_BIN_DIR, D_BIN_ID, 'adc')


@pytest.fixture
def d_roi_path():
    return _bin_path(D_BIN_DIR, D_BIN_ID, 'roi')


@pytest.fixture
def d_adc_bytes(d_adc_path):
    with open(d_adc_path, 'rb') as f:
        return f.read()


@pytest.fixture
def d_roi_bytes(d_roi_path):
    with open(d_roi_path, 'rb') as f:
        return f.read()


@pytest.fixture
def i_hdr_path():
    return _bin_path(I_BIN_DIR, I_BIN_ID, 'hdr')


@pytest.fixture
def i_adc_path():
    return _bin_path(I_BIN_DIR, I_BIN_ID, 'adc')


@pytest.fixture
def i_roi_path():
    return _bin_path(I_BIN_DIR, I_BIN_ID, 'roi')


@pytest.fixture
def i_adc_bytes(i_adc_path):
    with open(i_adc_path, 'rb') as f:
        return f.read()


@pytest.fixture
def i_roi_bytes(i_roi_path):
    with open(i_roi_path, 'rb') as f:
        return f.read()
