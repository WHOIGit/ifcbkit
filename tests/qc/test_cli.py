"""The ifcbkit-qc command line: output shape and exit codes."""

import json

import pytest

from ifcbkit.qc import Finding
from ifcbkit.qc.cli import EXIT_FAILED, EXIT_FINDINGS, EXIT_OK, main

from .fixtures import D_BIN_ID, copy_fileset, remove_file, set_hdr_key


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
    status, out, _ = run(capsys, basepath, '--only', 'adc_zero_geometry')
    assert status == EXIT_OK
    assert 'adc_zero_geometry' in out
    assert 'missing_roi' not in out


def test_unknown_code_fails_cleanly(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    status, _, err = run(capsys, basepath, '--ignore', 'no_such_check')
    assert status == EXIT_FAILED
    assert 'unknown check code' in err


def test_missing_path_fails_cleanly(tmp_path, capsys):
    status, _, err = run(capsys, str(tmp_path / 'nope'))
    assert status == EXIT_FAILED
    assert 'nope' in err


def test_json_output_is_one_finding_per_line(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    remove_file(basepath, 'roi')
    status, out, _ = run(capsys, basepath, '--json')
    assert status == EXIT_FINDINGS

    findings = [Finding.from_dict(json.loads(line))
                for line in out.splitlines()]
    assert 'missing_roi' in {f.code for f in findings}
    assert all(f.subject == D_BIN_ID for f in findings)


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


def test_truncation_and_skips_are_visible(tmp_path, capsys):
    basepath = copy_fileset(tmp_path)
    features = tmp_path / D_BIN_ID / f'{D_BIN_ID}_class.h5'
    features.write_bytes(b'not an hdf5 file')
    status, out, _ = run(capsys, basepath, '--cost', 'full')
    assert status in (EXIT_OK, EXIT_FINDINGS)
    # Either h5py reported a corrupt container, or it is not installed and the
    # class checks are reported as skipped. Both must be visible, not silent.
    assert 'product_container_corrupt' in out or 'skipped' in out
