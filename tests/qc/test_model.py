"""Report aggregation and cost-tier comparison."""

from ifcbkit.qc import Cost, Report, Severity, cost_allows
from ifcbkit.qc.registry import finding

BIN_ID = 'D20130526T095207_IFCB013'


def _report(*codes_and_details):
    report = Report(subject=BIN_ID, cost=Cost.PARSE)
    for code, detail in codes_and_details:
        report.findings.append(finding(code, BIN_ID, **detail))
    return report


def test_cost_allows_is_ordered():
    assert cost_allows(Cost.FULL, Cost.STAT)
    assert cost_allows(Cost.FULL, Cost.FULL)
    assert cost_allows(Cost.PARSE, Cost.STAT)
    assert not cost_allows(Cost.PARSE, Cost.FULL)
    assert not cost_allows(Cost.STAT, Cost.PARSE)


def test_severity_partitions_and_ok():
    report = _report(
        ('missing_adc', {}),
        ('hdr_missing_keys', {'missing': 'temperature'}),
        ('zero_rois', {'n_triggers': 0}),
    )
    assert [f.code for f in report.errors] == ['missing_adc']
    assert [f.code for f in report.warnings] == ['hdr_missing_keys']
    assert [f.code for f in report.infos] == ['zero_rois']
    assert not report.ok

    clean = _report(('zero_rois', {'n_triggers': 0}))
    assert clean.ok


def test_counts_and_codes():
    report = _report(
        ('adc_blank_line', {'line': 3}),
        ('adc_blank_line', {'line': 9}),
        ('zero_rois', {'n_triggers': 0}),
    )
    assert report.counts_by_code() == {'adc_blank_line': 2, 'zero_rois': 1}
    assert report.codes == {'adc_blank_line', 'zero_rois'}
    assert report.counts_by_severity()[Severity.ERROR] == 2


def test_extend_absorbs_findings_and_skips():
    a = _report(('missing_adc', {}))
    b = _report(('zero_rois', {'n_triggers': 0}))
    b.skipped['class_bad_values'] = 'h5py is not installed'
    a.extend(b)
    assert [f.code for f in a.findings] == ['missing_adc', 'zero_rois']
    assert a.skipped == {'class_bad_values': 'h5py is not installed'}


def test_to_jsonl_is_one_object_per_finding():
    import json

    report = _report(('missing_adc', {}), ('missing_roi', {}))
    lines = report.to_jsonl().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)['code'] for line in lines] == \
        ['missing_adc', 'missing_roi']
