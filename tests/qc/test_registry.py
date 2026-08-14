"""The registry is the catalogue; these tests keep it well-formed."""

import pytest

from ifcbkit.qc import (
    CHECKS,
    Cost,
    GROUPS,
    OPT_IN_CHECKS,
    OPT_IN_REASON,
    Report,
    Severity,
    codes_for_group,
    spec_for,
)
from ifcbkit.qc.registry import finding, note_opt_in_skips, resolve_opt_ins


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


def test_opt_in_checks_are_derived_from_the_specs():
    assert set(OPT_IN_CHECKS) == {
        code for code, spec in CHECKS.items() if spec.opt_in}
    # Both current ones fire on ordinary, undamaged data.
    assert set(OPT_IN_CHECKS) == {'adc_zero_geometry', 'mixed_instruments'}


def test_resolve_opt_ins_rejects_default_on_checks():
    assert resolve_opt_ins(()) == frozenset()
    assert resolve_opt_ins('all') == frozenset(OPT_IN_CHECKS)
    assert resolve_opt_ins(['mixed_instruments']) == {'mixed_instruments'}
    with pytest.raises(ValueError, match='not an opt-in check'):
        resolve_opt_ins(['missing_adc'])
    with pytest.raises(KeyError, match='unregistered QC check code'):
        resolve_opt_ins(['no_such_check'])


def test_note_opt_in_skips_accounts_for_what_it_did_not_run():
    report = Report(subject='D20130526T095207_IFCB013', cost=Cost.PARSE)
    note_opt_in_skips(report, GROUPS, frozenset())
    assert set(report.skipped) == set(OPT_IN_CHECKS)
    assert set(report.skipped.values()) == {OPT_IN_REASON}

    enabled = Report(subject='D20130526T095207_IFCB013', cost=Cost.PARSE)
    note_opt_in_skips(enabled, GROUPS, frozenset(OPT_IN_CHECKS))
    assert enabled.skipped == {}


def test_finding_round_trips_through_json():
    from ifcbkit.qc import Finding

    f = finding('roi_short_read', 'IFCB5_2012_028_081515',
                target=7, needed=100, offset=50, available=10)
    assert Finding.from_dict(f.to_dict()) == f
