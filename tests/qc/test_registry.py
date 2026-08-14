"""The registry is the catalogue; these tests keep it well-formed."""

import pytest

from ifcbkit.qc import CHECKS, Cost, GROUPS, Severity, codes_for_group, spec_for
from ifcbkit.qc.registry import finding


def test_codes_are_unique_and_self_consistent():
    for code, spec in CHECKS.items():
        assert spec.code == code


def test_every_spec_is_well_formed():
    for code, spec in CHECKS.items():
        assert isinstance(spec.severity, Severity), code
        assert isinstance(spec.cost, Cost), code
        assert spec.group in GROUPS, code
        assert spec.summary.strip(), code
        assert spec.template.strip(), code


def test_groups_partition_the_registry():
    grouped = [code for group in GROUPS for code in codes_for_group(group)]
    assert sorted(grouped) == sorted(CHECKS)


def test_unregistered_code_cannot_be_emitted():
    with pytest.raises(KeyError, match='unregistered QC check code'):
        spec_for('no_such_check')
    with pytest.raises(KeyError, match='unregistered QC check code'):
        finding('no_such_check', 'D20130526T095207_IFCB013')


def test_finding_takes_severity_from_the_registry():
    f = finding('missing_adc', 'D20130526T095207_IFCB013',
                path='/data/D20130526T095207_IFCB013.adc')
    assert f.severity is Severity.ERROR
    assert f.code == 'missing_adc'
    assert f.message == CHECKS['missing_adc'].summary
    assert f.path.endswith('.adc')


def test_finding_renders_the_template_from_detail():
    f = finding('adc_blank_line', 'D20130526T095207_IFCB013', line=42)
    assert '42' in f.message
    assert f.detail == {'line': 42}


def test_finding_round_trips_through_json():
    from ifcbkit.qc import Finding

    f = finding('roi_short_read', 'IFCB5_2012_028_081515',
                target=7, needed=100, offset=50, available=10)
    assert Finding.from_dict(f.to_dict()) == f
