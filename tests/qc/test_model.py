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


def _truncating_report(code, n, **detail):
    """Return a report that listed one finding of ``code`` and truncated n-1."""
    report = Report(subject=BIN_ID, cost=Cost.PARSE, max_per_code=1)
    for i in range(n):
        report.add(finding(code, BIN_ID, **{**detail, 'line': i + 1}))
    return report


def test_extend_sums_truncation_counts():
    # Both reports hid findings of the same code; the merge must not report
    # only one report's worth of hidden findings.
    a = _truncating_report('adc_blank_line', 4)
    b = _truncating_report('adc_blank_line', 3)
    assert (a.truncated, b.truncated) == ({'adc_blank_line': 3},
                                          {'adc_blank_line': 2})
    a.extend(b)
    assert a.truncated == {'adc_blank_line': 5}
    assert a.total_for('adc_blank_line') == 7


def test_filtered_filters_skips_and_truncation_with_the_findings():
    report = _truncating_report('adc_blank_line', 3)
    report.skipped['class_bad_values'] = 'h5py is not installed'
    report.truncated['features_ragged_rows'] = 4

    kept = report.filtered(only={'adc_blank_line'})
    assert [f.code for f in kept.findings] == ['adc_blank_line']
    assert kept.truncated == {'adc_blank_line': 2}
    assert kept.skipped == {}
    assert kept.total_for('adc_blank_line') == 3

    dropped = report.filtered(ignore={'adc_blank_line'})
    assert dropped.findings == []
    assert dropped.truncated == {'features_ragged_rows': 4}
    assert dropped.skipped == {'class_bad_values': 'h5py is not installed'}


def test_filtered_shares_nothing_with_the_original():
    report = _truncating_report('adc_blank_line', 2)
    report.skipped['class_bad_values'] = 'h5py is not installed'

    copy = report.filtered(only={'adc_blank_line'})
    copy.findings.clear()
    copy.skipped.clear()
    copy.truncated.clear()

    assert [f.code for f in report.findings] == ['adc_blank_line']
    assert report.skipped == {'class_bad_values': 'h5py is not installed'}
    assert report.truncated == {'adc_blank_line': 1}


def test_to_jsonl_is_an_envelope_then_one_object_per_finding():
    import json

    report = _report(('missing_adc', {}), ('missing_roi', {}))
    records = [json.loads(line) for line in report.to_jsonl().splitlines()]
    assert [r['type'] for r in records] == ['report', 'finding', 'finding']
    assert [r['code'] for r in records[1:]] == ['missing_adc', 'missing_roi']

    envelope = records[0]
    assert envelope['subject'] == BIN_ID
    assert envelope['cost'] == 'parse'
    assert (envelope['n_findings'], envelope['n_errors']) == (2, 2)


def test_to_jsonl_carries_skips_and_truncation():
    """The whole point: a findings-only stream reads a skip as a pass."""
    import json

    report = _truncating_report('adc_blank_line', 4)
    report.skipped['class_bad_values'] = 'h5py is not installed'
    envelope = json.loads(report.to_jsonl().splitlines()[0])

    assert envelope['skipped'] == {'class_bad_values': 'h5py is not installed'}
    assert envelope['truncated'] == {'adc_blank_line': 3}


def test_to_jsonl_records_a_subject_with_no_findings():
    """A clean subject must still leave a trace: checked is not the same as
    never looked at."""
    import json

    report = Report(subject=BIN_ID, cost=Cost.FULL)
    records = [json.loads(line) for line in report.to_jsonl().splitlines()]
    assert len(records) == 1
    assert records[0]['type'] == 'report'
    assert records[0]['n_findings'] == 0
