"""The ifcbkit-qc command line: output shape and exit codes."""

import json

import pytest

from ifcbkit.qc import Finding
from ifcbkit.qc.cli import EXIT_FAILED, EXIT_FINDINGS, EXIT_OK, main

from .fixtures import (
    D_BIN_ID,
    copy_fileset,
    read_adc_lines,
    remove_file,
    set_hdr_key,
    write_adc_lines,
)


def run(capsys, *argv):
    """Run the CLI, returning (status, stdout, stderr)."""
    status = main(list(argv))
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_clean_bin_exits_zero(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, out, _ = run(capsys, basepath)
    assert status == EXIT_OK
    assert D_BIN_ID in out
    assert '1 subject(s) checked, 0 with errors' in out


def test_damaged_bin_exits_one(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')
    status, out, _ = run(capsys, basepath)
    assert status == EXIT_FINDINGS
    assert 'missing_roi' in out


def test_warnings_only_exit_zero_unless_strict(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'sampleTime', '2013-05-26T11:52:07Z')

    status, out, _ = run(capsys, basepath)
    assert status == EXIT_OK
    assert 'hdr_pid_time_mismatch' in out

    strict_status, _, _ = run(capsys, basepath, '--strict')
    assert strict_status == EXIT_FINDINGS


def test_ignore_can_clear_the_only_failing_code(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')
    status, out, _ = run(capsys, basepath, '--ignore', 'missing_roi')
    assert status == EXIT_OK
    assert 'missing_roi' not in out


def test_only_restricts_to_named_codes(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')
    remove_file(basepath, 'hdr')
    status, out, _ = run(capsys, basepath, '--only', 'missing_hdr')
    assert status == EXIT_FINDINGS
    assert 'missing_hdr' in out
    assert 'missing_roi' not in out


def test_opt_in_checks_are_off_until_enabled(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)

    _, default_out, _ = run(capsys, basepath)
    assert 'no findings' in default_out
    # Named once for the run, not indented under the subject.
    assert 'not run for any subject: adc_zero_geometry' in default_out

    _, enabled_out, _ = run(capsys, basepath, '--enable', 'adc_zero_geometry')
    assert 'info     adc_zero_geometry' in enabled_out
    assert 'not run for any subject' not in enabled_out


def test_enable_all_turns_on_every_opt_in_check(tmp_path, capsys):
    from ifcbkit.qc import OPT_IN_CHECKS

    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    copy_fileset(root, D_BIN_ID, into='D20130526',
                 new_bin_id='D20130526T095208_IFCB014')

    _, out, _ = run(capsys, str(root), '--enable', 'all')
    for code in OPT_IN_CHECKS:
        assert f'skipped  {code}' not in out
    assert 'mixed_instruments' in out
    assert 'adc_zero_geometry' in out


def _tree_with_one_bad_bin(tmp_path):
    """Three clean bins and one missing its .roi. Returns the tree root."""
    root = tmp_path / 'data'
    for hour in ('T095207', 'T105207', 'T115207', 'T125207'):
        copy_fileset(root, D_BIN_ID, into='D20130526',
                     new_bin_id=f'D20130526{hour}_IFCB013')
    remove_file(str(root / 'D20130526' / 'D20130526T125207_IFCB013'), 'roi')
    return root


def test_quiet_prints_only_subjects_with_something_to_report(tmp_path, capsys):
    root = _tree_with_one_bad_bin(tmp_path)

    _, full_out, _ = run(capsys, str(root), '--ignore', 'hdr_pid_time_mismatch')
    assert full_out.count('no findings') == 3  # the 3 intact bins

    status, quiet_out, _ = run(
        capsys, str(root), '--quiet', '--ignore', 'hdr_pid_time_mismatch')
    assert status == EXIT_FINDINGS
    assert 'no findings' not in quiet_out
    assert 'missing_roi' in quiet_out
    assert 'D20130526T125207_IFCB013' in quiet_out
    assert 'D20130526T095207_IFCB013' not in quiet_out


def test_quiet_still_accounts_for_every_subject(tmp_path, capsys):
    """Hiding clean subjects must not hide that they were checked."""
    root = _tree_with_one_bad_bin(tmp_path)
    _, out, _ = run(capsys, str(root), '--quiet',
                    '--ignore', 'hdr_pid_time_mismatch')
    # The tree report also flags the gap, so two subjects carry the error.
    assert '5 subject(s) checked, 2 with errors' in out
    assert '(3 with nothing to report, not shown)' in out
    # The run-wide opt-in note survives too.
    assert 'not run for any subject: adc_zero_geometry' in out


def test_quiet_does_not_hide_a_subject_whose_check_was_skipped(tmp_path,
                                                              capsys):
    """A skipped check is the report saying it does not know — never clean."""
    basepath = copy_fileset(tmp_path)
    # A partial ADCFileFormat declaration cannot be compared against the
    # layout, so that check is skipped while the bin is otherwise fine.
    set_hdr_key(basepath, 'ADCFileFormat', 'trigger,ROIx,ROIy')

    _, out, _ = run(capsys, basepath, '--quiet')
    assert D_BIN_ID in out
    assert 'skipped  adc_format_declaration_mismatch' in out
    assert 'not shown' not in out


def test_quiet_on_a_wholly_clean_tree_prints_just_the_summary(tmp_path, capsys):
    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')

    status, out, _ = run(capsys, str(root), '--quiet')
    assert status == EXIT_OK
    assert D_BIN_ID not in out
    assert '2 subject(s) checked, 0 with errors' in out
    assert '(2 with nothing to report, not shown)' in out


def test_roi_optional_stops_pending_telemetry_being_an_error(tmp_path, capsys):
    """.roi files can lag the .hdr and .adc, so their absence is not damage."""
    root = tmp_path / 'data'
    for hour in ('T095207', 'T105207'):
        copy_fileset(root, D_BIN_ID, into='D20130526',
                     new_bin_id=f'D20130526{hour}_IFCB013')
        remove_file(str(root / 'D20130526' / f'D20130526{hour}_IFCB013'), 'roi')

    status, out, _ = run(capsys, str(root))
    assert status == EXIT_FINDINGS
    assert 'missing_roi' in out
    assert 'fileset_incomplete' in out

    ok_status, ok_out, _ = run(capsys, str(root), '--roi-optional')
    assert ok_status == EXIT_OK
    assert '0 with errors' in ok_out
    assert 'fileset_incomplete' not in ok_out
    # Not an error, but not verified either.
    assert 'skipped  missing_roi' in ok_out
    assert 'ADC-to-ROI checks could not run' in ok_out


def test_roi_optional_still_reports_a_truly_incomplete_fileset(tmp_path,
                                                               capsys):
    """The distinction --ignore fileset_incomplete could not make."""
    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    basepath = str(root / 'D20130526' / D_BIN_ID)
    remove_file(basepath, 'roi')
    remove_file(basepath, 'adc')

    status, out, _ = run(capsys, str(root), '--roi-optional')
    assert status == EXIT_FINDINGS
    assert 'missing_adc' in out
    assert 'fileset_incomplete' in out
    assert 'missing .adc' in out
    # Reported as an absence to account for, never as an error.
    assert 'error    missing_roi' not in out
    assert 'skipped  missing_roi' in out


def test_roi_optional_appears_in_the_json_run_record(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')

    status, out, _ = run(capsys, basepath, '--json', '--roi-optional')
    assert status == EXIT_OK
    run_record, envelopes, findings = json_records(out)
    assert run_record['roi_optional'] is True
    assert findings == []
    assert 'missing_roi' in envelopes[0]['skipped']


def test_enabling_a_default_check_fails_cleanly(tmp_path, capsys):
    """Naming a default-on check is a mistake worth reporting, not a no-op."""
    basepath = copy_fileset(tmp_path)
    status, _, err = run(capsys, basepath, '--enable', 'missing_roi')
    assert status == EXIT_FAILED
    assert 'run by default' in err


def test_unknown_enable_code_fails_cleanly(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, _, err = run(capsys, basepath, '--enable', 'no_such_check')
    assert status == EXIT_FAILED
    assert 'unknown check code' in err


def test_unknown_code_fails_cleanly(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, _, err = run(capsys, basepath, '--ignore', 'no_such_check')
    assert status == EXIT_FAILED
    assert 'unknown check code' in err


def test_missing_path_fails_cleanly(tmp_path, capsys):
    status, _, err = run(capsys, str(tmp_path / 'nope'))
    assert status == EXIT_FAILED
    assert 'nope' in err


def json_records(out):
    """Split JSON Lines output into (run_record, envelopes, findings)."""
    records = [json.loads(line) for line in out.splitlines()]
    assert all('type' in record for record in records)
    runs = [r for r in records if r['type'] == 'run']
    assert len(runs) == 1 and records[0] is runs[0], 'one run record, first'
    return (runs[0],
            [r for r in records if r['type'] == 'report'],
            [r for r in records if r['type'] == 'finding'])


def test_json_output_is_an_envelope_plus_one_finding_per_line(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')
    status, out, _ = run(capsys, basepath, '--json')
    assert status == EXIT_FINDINGS

    _, envelopes, raw_findings = json_records(out)
    findings = [Finding.from_dict(record) for record in raw_findings]
    assert 'missing_roi' in {f.code for f in findings}
    assert all(f.subject == D_BIN_ID for f in findings)

    assert [e['subject'] for e in envelopes] == [D_BIN_ID]
    assert envelopes[0]['n_findings'] == len(findings)


def test_json_names_run_wide_skips_once(tmp_path, capsys):
    """A skipped check and a passed check must not look alike to a consumer.

    But which opt-in checks went unrequested is a property of the command line,
    so it belongs to the run, not repeated on every subject in the archive.
    """
    root = tmp_path / 'data'
    for hour in ('T095207', 'T105207', 'T115207'):
        copy_fileset(root, D_BIN_ID, into='D20130526',
                     new_bin_id=f'D20130526{hour}_IFCB013')
    _, out, _ = run(capsys, str(root), '--json')

    run_record, envelopes, _ = json_records(out)
    assert set(run_record['skipped']) == {'adc_zero_geometry',
                                          'mixed_instruments'}
    assert run_record['n_subjects'] == len(envelopes) == 4  # tree plus 3 bins
    # Said once, not four times.
    assert all('skipped' not in envelope for envelope in envelopes)


def test_json_records_a_clean_subject(tmp_path, capsys):
    """Silence is not health: a clean bin still gets a record of its own."""
    basepath = copy_fileset(tmp_path)
    status, out, _ = run(capsys, basepath, '--json')
    assert status == EXIT_OK

    run_record, envelopes, findings = json_records(out)
    assert findings == []
    assert [(e['subject'], e['n_findings'], e['n_errors'])
            for e in envelopes] == [(D_BIN_ID, 0, 0)]
    # Nothing per-subject to say, so the record stays to the point.
    assert 'skipped' not in envelopes[0]
    assert 'truncated' not in envelopes[0]
    # The opt-in check nobody ran is still on the record, once, for the run.
    assert 'adc_zero_geometry' in run_record['skipped']


def test_json_reports_truncated_findings(tmp_path, capsys):
    """50 listed findings must not make a 250-line failure look like 50."""
    from ifcbkit.qc import MAX_FINDINGS_PER_CODE

    basepath = copy_fileset(tmp_path)
    extra = 200
    write_adc_lines(
        basepath, read_adc_lines(basepath) + ['1,2,3'] * extra)

    _, out, _ = run(capsys, basepath, '--json')
    _, envelopes, findings = json_records(out)
    code = 'adc_column_count_mismatch'

    listed = [f for f in findings if f['code'] == code]
    assert len(listed) == MAX_FINDINGS_PER_CODE
    assert envelopes[0]['truncated'][code] == extra - MAX_FINDINGS_PER_CODE


def test_list_checks_covers_the_registry(capsys):
    from ifcbkit.qc import CHECKS

    status, out, _ = run(capsys, '--list-checks')
    assert status == EXIT_OK
    for code in CHECKS:
        assert code in out


def test_no_paths_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cost_flag_changes_what_runs(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    set_hdr_key(basepath, 'imagerID', 99)
    _, stat_out, _ = run(capsys, basepath, '--cost', 'stat')
    _, parse_out, _ = run(capsys, basepath, '--cost', 'parse')
    assert 'hdr_pid_instrument_mismatch' not in stat_out
    assert 'hdr_pid_instrument_mismatch' in parse_out


def test_expect_reports_missing_products(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, out, _ = run(capsys, basepath, '--expect', 'features,blobs')
    assert status == EXIT_FINDINGS
    assert out.count('product_missing') == 2


def test_product_dir_points_products_outside_the_raw_tree(tmp_path, capsys):
    from .test_products import (
        clean_feature_rows,
        write_features,
    )

    basepath = copy_fileset(tmp_path / 'raw', D_BIN_ID, into='D20130526')
    features_root = tmp_path / 'features'
    (features_root / 'D20130526').mkdir(parents=True)
    write_features(features_root / 'D20130526', clean_feature_rows())

    # Cost.STAT: discovery is what is under test, not the CSV contents.
    status, out, _ = run(
        capsys, basepath, '--expect', 'features', '--cost', 'stat',
        '--product-dir', f'features={features_root}')
    assert status == EXIT_OK
    assert 'product_missing' not in out

    # Without the mapping the same bin has no features at all.
    missing_status, missing_out, _ = run(
        capsys, basepath, '--expect', 'features', '--cost', 'stat')
    assert missing_status == EXIT_FINDINGS
    assert 'product_missing' in missing_out


def test_products_root_covers_every_product_type(tmp_path, capsys):
    basepath = copy_fileset(tmp_path / 'raw', D_BIN_ID, into='D20130526')
    status, out, _ = run(
        capsys, basepath, '--expect', 'features',
        '--products-root', str(tmp_path / 'products'))
    assert status == EXIT_FINDINGS
    assert str(tmp_path / 'products') in out


def test_bad_product_dir_spec_fails_cleanly(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, _, err = run(capsys, basepath, '--product-dir', '/some/path')
    assert status == EXIT_FAILED
    assert '--product-dir expects TYPE=PATH' in err


def test_unknown_product_fails_cleanly(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, _, err = run(capsys, basepath, '--expect', 'featuers')
    assert status == EXIT_FAILED
    assert 'unknown product' in err


def test_tree_mode_checks_the_collection_and_every_bin(tmp_path, capsys):
    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    copy_fileset(root, D_BIN_ID, into='D20130526',
                 new_bin_id='D20130526T105207_IFCB013')
    remove_file(str(root / 'D20130526' / 'D20130526T105207_IFCB013'), 'roi')

    status, out, _ = run(capsys, str(root))
    assert status == EXIT_FINDINGS
    # One collection report plus one report per bin.
    assert '3 subject(s) checked' in out
    assert 'fileset_incomplete' in out
    assert str(root) in out


def test_a_crash_on_one_bin_does_not_lose_the_others(tmp_path, capsys,
                                                     monkeypatch):
    """An unforeseen exception is a finding about one bin, not a dead scan."""
    from ifcbkit.qc import cli as cli_mod

    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    copy_fileset(root, D_BIN_ID, into='D20130526',
                 new_bin_id='D20130526T105207_IFCB013')

    real_check_bin = cli_mod.check_bin

    def exploding(path, **kwargs):
        if 'T105207' in str(path):
            raise RuntimeError('boom')
        return real_check_bin(path, **kwargs)

    monkeypatch.setattr(cli_mod, 'check_bin', exploding)
    status, out, _ = run(capsys, str(root))

    assert status == EXIT_FINDINGS
    assert 'check_failed' in out
    assert 'RuntimeError: boom' in out
    # Both bins and the collection still produced a report, and only the
    # crashed one counts as bad.
    assert '3 subject(s) checked, 1 with errors' in out
    assert 'D20130526T095207_IFCB013' in out


def test_tree_mode_does_not_recursively_search_product_roots(tmp_path, capsys):
    """The recursive fallback is per bin, so it is off for a tree by default."""
    from .test_products import clean_feature_rows, write_features

    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    unconventional = tmp_path / 'products' / 'batch-07'
    unconventional.mkdir(parents=True)
    write_features(unconventional, clean_feature_rows())

    common = (str(root), '--expect', 'features', '--cost', 'stat',
              '--products-root', str(tmp_path / 'products'))
    _, auto_out, _ = run(capsys, *common)
    assert 'product_missing' in auto_out

    _, always_out, _ = run(capsys, *common, '--product-search', 'always')
    assert 'product_missing' not in always_out


def test_single_bin_mode_searches_product_roots_by_default(tmp_path, capsys):
    from .test_products import clean_feature_rows, write_features

    basepath = copy_fileset(tmp_path / 'data', D_BIN_ID, into='D20130526')
    unconventional = tmp_path / 'products' / 'batch-07'
    unconventional.mkdir(parents=True)
    write_features(unconventional, clean_feature_rows())

    common = (basepath, '--expect', 'features', '--cost', 'stat',
              '--products-root', str(tmp_path / 'products'))
    _, auto_out, _ = run(capsys, *common)
    assert 'product_missing' not in auto_out

    _, never_out, _ = run(capsys, *common, '--product-search', 'never')
    assert 'product_missing' in never_out


def test_truncation_and_skips_are_visible(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    features = tmp_path / D_BIN_ID / f'{D_BIN_ID}_class.h5'
    features.write_bytes(b'not an hdf5 file')
    status, out, _ = run(capsys, basepath, '--cost', 'full')
    assert status in (EXIT_OK, EXIT_FINDINGS)
    # Either h5py reported a corrupt container, or it is not installed and the
    # class checks are reported as skipped. Both must be visible, not silent.
    assert 'product_container_corrupt' in out or 'skipped' in out
