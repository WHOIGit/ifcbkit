"""Collection-level checks over a raw data tree."""

import os
from datetime import datetime, timezone

from ifcbkit.qc import Cost, Severity
from ifcbkit.qc.collection import check_collection, list_bins, walk_filesets

from .fixtures import D_BIN_ID, I_BIN_ID, copy_fileset, remove_file

OTHER_D_BIN = 'D20130527T095207_IFCB013'


def codes(report):
    return report.counts_by_code()


def detail_for(report, code):
    return next(f for f in report.findings if f.code == code).detail


def _tree(tmp_path):
    """Build ``<tmp>/data/`` with one bin in its correct day directory."""
    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    return root


def test_clean_tree_reports_nothing(tmp_path):
    report = check_collection(_tree(tmp_path))
    assert report.findings == []
    assert report.ok


def test_walk_yields_incomplete_filesets(tmp_path):
    root = _tree(tmp_path)
    remove_file(str(root / 'D20130526' / D_BIN_ID), 'roi')
    found = list(walk_filesets(root))
    assert [(bin_id, sorted(exts)) for _, bin_id, exts in found] == \
        [(D_BIN_ID, ['adc', 'hdr'])]


def test_fileset_incomplete_is_the_headline_check(tmp_path):
    root = _tree(tmp_path)
    remove_file(str(root / 'D20130526' / D_BIN_ID), 'roi')
    report = check_collection(root)
    incomplete = next(
        f for f in report.findings if f.code == 'fileset_incomplete')
    assert incomplete.severity is Severity.ERROR
    assert incomplete.detail['missing'] == '.roi'
    assert incomplete.detail['present'] == '.adc, .hdr'
    # sync_list_filesets cannot see this bin at all, which is the point.
    from ifcbkit.fileset import sync_list_filesets
    assert list(sync_list_filesets(str(root))) == []


def test_duplicate_pid(tmp_path):
    root = _tree(tmp_path)
    # 'data' is in DEFAULT_INCLUDE, so this second copy is walked rather than
    # dropped by the path rules.
    copy_fileset(root, D_BIN_ID, into='data')
    report = check_collection(root)
    duplicate = detail_for(report, 'duplicate_pid')
    assert duplicate['count'] == 2
    assert duplicate['bin_id'] == D_BIN_ID


def test_day_dir_mismatch(tmp_path):
    root = tmp_path / 'root'
    copy_fileset(root, D_BIN_ID, into='data')
    report = check_collection(root)
    mismatch = detail_for(report, 'day_dir_mismatch')
    assert (mismatch['actual'], mismatch['expected']) == ('data', 'D20130526')


def test_bin_named_directory_is_not_a_day_dir_mismatch(tmp_path):
    # tests/data itself is laid out this way, and resolve_fileset supports it.
    root = tmp_path / 'root'
    copy_fileset(root, D_BIN_ID)
    report = check_collection(root)
    assert 'day_dir_mismatch' not in codes(report)


def test_i_style_day_dir_is_accepted(tmp_path):
    root = tmp_path / 'data'
    copy_fileset(root, I_BIN_ID, into='IFCB5_2012_028')
    report = check_collection(root)
    assert 'day_dir_mismatch' not in codes(report)


def test_stray_files_are_info(tmp_path):
    root = _tree(tmp_path)
    (root / 'D20130526' / 'notes.txt').write_text('hello')
    report = check_collection(root)
    stray = next(f for f in report.findings if f.code == 'stray_files')
    assert stray.severity is Severity.INFO
    assert stray.detail['count'] == 1


def test_ds_store_is_not_a_stray(tmp_path):
    root = _tree(tmp_path)
    (root / 'D20130526' / '.DS_Store').write_bytes(b'\x00')
    report = check_collection(root)
    assert 'stray_files' not in codes(report)


def test_excluded_by_path_rules(tmp_path):
    root = _tree(tmp_path)
    (root / 'skip').mkdir()
    report = check_collection(root)
    excluded = detail_for(report, 'excluded_by_path_rules')
    assert excluded['rule'] == 'exclude'


def test_empty_day_dir(tmp_path):
    root = _tree(tmp_path)
    (root / 'D20130601').mkdir()
    report = check_collection(root)
    empty = next(f for f in report.findings if f.code == 'empty_day_dir')
    assert empty.path.endswith('D20130601')


def test_missing_days(tmp_path):
    root = _tree(tmp_path)
    copy_fileset(root, D_BIN_ID, into='D20130529',
                 new_bin_id='D20130529T095207_IFCB013')
    report = check_collection(root)
    missing = detail_for(report, 'missing_days')
    assert missing['count'] == 2  # the 27th and 28th
    assert missing['first'] == '2013-05-26'


def test_dropped_by_filter(tmp_path):
    root = _tree(tmp_path)
    report = check_collection(
        root, start_time=datetime(2020, 1, 1, tzinfo=timezone.utc))
    dropped = detail_for(report, 'dropped_by_filter')
    assert dropped['bin_id'] == D_BIN_ID
    assert dropped['filter_name'] == 'time'


def test_instrument_filter_drops_are_named(tmp_path):
    root = _tree(tmp_path)
    report = check_collection(root, instrument=99)
    assert detail_for(report, 'dropped_by_filter')['filter_name'] == 'instrument'


def test_mixed_instruments_is_opt_in(tmp_path):
    root = tmp_path / 'data'
    copy_fileset(root, D_BIN_ID, into='D20130526')
    copy_fileset(root, D_BIN_ID, into='D20130526',
                 new_bin_id='D20130526T095208_IFCB014')

    default_report = check_collection(root)
    assert 'mixed_instruments' not in codes(default_report)
    assert 'mixed_instruments' in default_report.skipped

    opted_in = check_collection(root, mixed_instruments=True)
    mixed = next(f for f in opted_in.findings if f.code == 'mixed_instruments')
    assert mixed.severity is Severity.INFO
    assert mixed.detail['instruments'] == '13, 14'


def test_adcmod_orphans(tmp_path):
    root = _tree(tmp_path)
    adcmod = tmp_path / 'adcmod' / 'D20130526'
    adcmod.mkdir(parents=True)
    (adcmod / f'{D_BIN_ID}.adc.mod').write_text('')
    (adcmod / f'{OTHER_D_BIN}.adc.mod').write_text('')

    report = check_collection(root, adcmod_root=tmp_path / 'adcmod')
    orphans = detail_for(report, 'adcmod_orphans')
    assert orphans['count'] == 1
    assert orphans['example'] == f'{OTHER_D_BIN}.adc.mod'


def test_list_bins_includes_partial_filesets(tmp_path):
    root = _tree(tmp_path)
    remove_file(str(root / 'D20130526' / D_BIN_ID), 'hdr')
    assert list_bins(root) == [
        (os.path.join(str(root), 'D20130526'), D_BIN_ID)]
