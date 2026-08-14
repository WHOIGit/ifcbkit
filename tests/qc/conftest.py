"""Session-wide enforcement that every registered check is actually reachable.

The registry is the catalogue, and a catalogue entry nobody can trigger is a
lie. Every ``finding()`` call made during the QC test session is recorded here;
when the whole ``tests/qc`` directory runs and passes, any registered code that
never fired fails the session.

This is deliberately a session hook rather than a test: it can only be judged
once everything has run, and it must not fire on a filtered run (``-k``, a
single file) where most checks were never given a chance.
"""

import os

import pytest

from ifcbkit.qc import CHECKS
from ifcbkit.qc import collection as collection_mod
from ifcbkit.qc import products as products_mod
from ifcbkit.qc import raw as raw_mod
from ifcbkit.qc import registry as registry_mod

# Codes emitted anywhere during this session.
EMITTED_CODES: set = set()

# The modules that hold a direct reference to registry.finding.
_PATCH_TARGETS = (registry_mod, raw_mod, products_mod, collection_mod)

# Test modules in this directory, filled in at collection time.
_COLLECTED_FILES: set = set()

# Checks that can only be exercised with an optional dependency installed.
# Exempt from the parity requirement when that dependency is absent — the
# checks themselves degrade to Report.skipped in that case, which
# test_class_checks_are_skipped_without_h5py covers.
_OPTIONAL_DEPENDENCY_CODES = {
    'h5py': ('class_missing_dataset', 'class_shape_mismatch',
             'class_bad_values', 'class_roi_mismatch'),
}


def _unavailable_codes() -> set:
    """Return codes exempt from parity because their dependency is missing."""
    import importlib.util

    exempt = set()
    for module, codes in _OPTIONAL_DEPENDENCY_CODES.items():
        if importlib.util.find_spec(module) is None:
            exempt.update(codes)
    return exempt


@pytest.fixture(autouse=True, scope='session')
def _record_emitted_codes():
    """Wrap ``registry.finding`` so every emitted code is recorded."""
    original = registry_mod.finding

    def recording_finding(code, subject, **kwargs):
        EMITTED_CODES.add(code)
        return original(code, subject, **kwargs)

    for module in _PATCH_TARGETS:
        if getattr(module, 'finding', None) is original:
            module.finding = recording_finding
    try:
        yield
    finally:
        for module in _PATCH_TARGETS:
            if getattr(module, 'finding', None) is recording_finding:
                module.finding = original


def pytest_collection_modifyitems(items):
    """Remember which test files in this directory were collected."""
    here = os.path.dirname(__file__)
    for item in items:
        path = str(getattr(item, 'fspath', ''))
        if os.path.dirname(path) == here:
            _COLLECTED_FILES.add(os.path.basename(path))


def _is_full_qc_run() -> bool:
    """True if every test module in this directory was collected."""
    here = os.path.dirname(__file__)
    expected = {name for name in os.listdir(here)
                if name.startswith('test_') and name.endswith('.py')}
    return expected and expected <= _COLLECTED_FILES


def pytest_sessionfinish(session, exitstatus):
    """Fail the session if a registered check was never emitted."""
    if exitstatus != 0 or not _is_full_qc_run():
        return
    missing = sorted(set(CHECKS) - EMITTED_CODES - _unavailable_codes())
    if missing:
        session.exitstatus = 1
        print('\nQC checks registered but never emitted by any test:')
        for code in missing:
            print(f'  {code}')
