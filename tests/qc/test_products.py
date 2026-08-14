"""Product checks, and the invariant that keeps them honest.

QC reads product containers tolerantly so it can say which row is bad. The
strict readers in ifcbkit.products stop at the first bad row. The two must
agree on whether a file is usable, which is what
:func:`test_clean_products_do_not_raise_in_the_strict_readers` and
:func:`test_files_qc_rejects_also_break_the_strict_reader` pin down.
"""

import io

import pytest
from PIL import Image

from ifcbkit.products import read_blobs, read_features
from ifcbkit.qc import Cost, Severity
from ifcbkit.qc.products import check_products, find_products

BIN_ID = 'D20130526T095207_IFCB013'
TARGETS = (1, 2, 3)
FEATURE_COLUMNS = ('roi_number', 'Area', 'Biovolume')


def codes(report):
    return report.counts_by_code()


def detail_for(report, code):
    return next(f for f in report.findings if f.code == code).detail


def write_features(tmp_path, rows, *, columns=FEATURE_COLUMNS, version=4,
                   bin_id=BIN_ID):
    path = tmp_path / f'{bin_id}_fea_v{version}.csv'
    lines = [','.join(columns)] + [','.join(str(v) for v in row) for row in rows]
    path.write_text('\n'.join(lines) + '\n')
    return path


def clean_feature_rows(targets=TARGETS):
    return [(target, 100 + target, 200.5 + target) for target in targets]


def png_bytes(size=(4, 4)):
    buffer = io.BytesIO()
    Image.new('L', size, color=128).save(buffer, format='PNG')
    return buffer.getvalue()


def write_blobs(tmp_path, members, *, version=4, bin_id=BIN_ID):
    """Write a blob ZIP. ``members`` maps member name to PNG bytes."""
    from zipfile import ZipFile

    path = tmp_path / f'{bin_id}_blobs_v{version}.zip'
    with ZipFile(path, 'w') as archive:
        for name, data in members:
            archive.writestr(name, data)
    return path


def clean_blob_members(targets=TARGETS, bin_id=BIN_ID):
    return [(f'{bin_id}_{target:05d}.png', png_bytes()) for target in targets]


def write_class_scores(tmp_path, *, roi_numbers=TARGETS, labels=('a', 'b'),
                       scores=None, bin_id=BIN_ID, omit=()):
    h5py = pytest.importorskip('h5py')
    path = tmp_path / f'{bin_id}_class.h5'
    if scores is None:
        scores = [[0.25, 0.75] for _ in roi_numbers]
    with h5py.File(path, 'w') as handle:
        if 'output_scores' not in omit:
            handle.create_dataset('output_scores', data=scores)
        if 'class_labels' not in omit:
            handle.create_dataset(
                'class_labels', data=[label.encode('ascii') for label in labels])
        if 'roi_numbers' not in omit:
            handle.create_dataset('roi_numbers', data=list(roi_numbers))
    return path


# --- discovery, presence, versions ---

def test_find_products_reports_paths_and_versions(tmp_path):
    write_features(tmp_path, clean_feature_rows())
    write_blobs(tmp_path, clean_blob_members(), version=2)
    found = find_products(tmp_path, BIN_ID)
    assert found['features'][1] == 4
    assert found['blobs'][1] == 2
    assert 'class' not in found


def test_products_are_found_in_per_type_roots(tmp_path):
    # The production layout: one tree per product type, each organized by day.
    features_dir = tmp_path / 'features' / 'D20130526'
    blobs_dir = tmp_path / 'blobs' / '2013' / 'D20130526'
    features_dir.mkdir(parents=True)
    blobs_dir.mkdir(parents=True)
    write_features(features_dir, clean_feature_rows())
    write_blobs(blobs_dir, clean_blob_members())

    product_dirs = {'features': tmp_path / 'features',
                    'blobs': tmp_path / 'blobs'}
    found = find_products(None, BIN_ID, product_dirs=product_dirs)
    assert set(found) == {'features', 'blobs'}

    report = check_products(
        None, BIN_ID, targets=TARGETS, product_dirs=product_dirs)
    assert report.findings == []


def test_day_and_year_directories_are_found_without_searching(tmp_path):
    # --product-search never / search=False: conventions only, no walk.
    day_dir = tmp_path / 'D20130526'
    day_dir.mkdir()
    write_features(day_dir, clean_feature_rows())
    assert find_products(tmp_path, BIN_ID, search=False).keys() == {'features'}


def test_unconventional_layout_needs_the_recursive_fallback(tmp_path):
    odd = tmp_path / 'batch-07'
    odd.mkdir()
    write_features(odd, clean_feature_rows())
    assert find_products(tmp_path, BIN_ID, search=False) == {}
    assert find_products(tmp_path, BIN_ID).keys() == {'features'}


def test_unmapped_product_types_are_not_searched(tmp_path):
    # Only a features root given, so a blobs file next to the raw data is not
    # picked up: which directories to search is stated, never guessed.
    write_blobs(tmp_path, clean_blob_members())
    found = find_products(None, BIN_ID, product_dirs={'features': tmp_path})
    assert found == {}

    report = check_products(
        None, BIN_ID, expect=('blobs',), targets=TARGETS,
        product_dirs={'features': tmp_path})
    assert detail_for(report, 'product_missing')['searched'] == \
        '(no directory given)'


def test_highest_version_wins(tmp_path):
    write_features(tmp_path, clean_feature_rows(), version=2)
    write_features(tmp_path, clean_feature_rows(), version=4)
    path, version = find_products(tmp_path, BIN_ID)['features']
    assert version == 4
    assert path.endswith('_fea_v4.csv')


def test_product_missing_names_the_directory_searched(tmp_path):
    report = check_products(tmp_path, BIN_ID, expect=('features',))
    assert detail_for(report, 'product_missing')['searched'] == str(tmp_path)


def test_product_missing_only_for_declared_expectations(tmp_path):
    report = check_products(tmp_path, BIN_ID, expect=('features',))
    assert codes(report) == {'product_missing': 1}
    assert detail_for(report, 'product_missing')['product'] == 'features'

    quiet = check_products(tmp_path, BIN_ID)
    assert quiet.findings == []


def test_product_unexpected_version_is_a_warning(tmp_path):
    write_features(tmp_path, clean_feature_rows(), version=9)
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    unexpected = next(
        f for f in report.findings if f.code == 'product_unexpected_version')
    assert unexpected.severity is Severity.WARNING
    assert unexpected.detail['version'] == 9


def test_containers_are_not_opened_below_full_cost(tmp_path):
    write_features(tmp_path, [(1, 'not-a-number', 3)])
    report = check_products(tmp_path, BIN_ID, cost=Cost.PARSE, targets=TARGETS)
    assert 'features_non_numeric' not in codes(report)


# --- features ---

def test_clean_features_report_nothing(tmp_path):
    write_features(tmp_path, clean_feature_rows())
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert report.findings == []


def test_features_missing_header(tmp_path):
    path = tmp_path / f'{BIN_ID}_fea_v4.csv'
    path.write_text('')
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert 'features_missing_header' in codes(report)


def test_features_missing_roi_column(tmp_path):
    write_features(tmp_path, [(1, 2, 3)], columns=('id', 'Area', 'Biovolume'))
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert 'Area' in detail_for(report, 'features_missing_roi_column')['columns']


def test_features_roi_column_camel_case_is_accepted(tmp_path):
    write_features(tmp_path, clean_feature_rows(),
                   columns=('roiNumber', 'Area', 'Biovolume'))
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert report.findings == []


def test_features_ragged_rows(tmp_path):
    write_features(tmp_path, [(1, 100, 200.5), (2, 100)])
    report = check_products(tmp_path, BIN_ID, targets=(1, 2))
    ragged = detail_for(report, 'features_ragged_rows')
    assert (ragged['row'], ragged['n_fields'], ragged['n_columns']) == (3, 2, 3)


def test_features_non_numeric(tmp_path):
    write_features(tmp_path, [(1, 'wide', 200.5)])
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    non_numeric = detail_for(report, 'features_non_numeric')
    assert (non_numeric['column'], non_numeric['value']) == ('Area', 'wide')


def test_features_empty_roi_number(tmp_path):
    write_features(tmp_path, [('', 100, 200.5)])
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    assert detail_for(report, 'features_empty_roi_number')['row'] == 2


def test_features_duplicate_rois(tmp_path):
    write_features(tmp_path, [(1, 1, 1), (1, 2, 2), (2, 3, 3)])
    report = check_products(tmp_path, BIN_ID, targets=(1, 2))
    duplicate = detail_for(report, 'features_duplicate_rois')
    assert (duplicate['count'], duplicate['example']) == (1, 1)


def test_features_roi_not_in_bin_and_coverage(tmp_path):
    write_features(tmp_path, [(1, 1, 1), (99, 2, 2)])
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'features_roi_not_in_bin')['example'] == 99
    coverage = detail_for(report, 'features_roi_coverage')
    assert (coverage['covered'], coverage['total']) == (1, 3)


def test_coverage_is_skipped_without_targets(tmp_path):
    write_features(tmp_path, clean_feature_rows())
    report = check_products(tmp_path, BIN_ID)
    assert 'features_roi_coverage' in report.skipped
    assert 'features_roi_coverage' not in codes(report)


def test_features_container_unreadable(tmp_path):
    import os

    if os.geteuid() == 0:
        pytest.skip('root can read a mode-000 file')
    path = write_features(tmp_path, clean_feature_rows())
    os.chmod(path, 0o000)
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'product_container_corrupt')['product'] == 'features'


# --- blobs ---

def test_clean_blobs_report_nothing(tmp_path):
    write_blobs(tmp_path, clean_blob_members())
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert report.findings == []


def test_blobs_bad_roi_id(tmp_path):
    write_blobs(tmp_path, [('not-an-roi-id.png', png_bytes())])
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'blobs_bad_roi_id')['member'] == 'not-an-roi-id'


def test_blobs_pid_mismatch(tmp_path):
    other = 'D20130526T095207_IFCB014'
    write_blobs(tmp_path, [(f'{other}_00001.png', png_bytes())])
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'blobs_pid_mismatch')['member_bin'] == other


def test_blobs_duplicate_members(tmp_path):
    members = clean_blob_members(targets=(1,))
    write_blobs(tmp_path, members + [(f'sub/{BIN_ID}_00001.png', png_bytes())])
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    assert detail_for(report, 'blobs_duplicate_members')['count'] == 1


def test_blobs_png_decode_failure(tmp_path):
    write_blobs(tmp_path, [(f'{BIN_ID}_00001.png', b'not a png')])
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    assert detail_for(report, 'blobs_png_decode_failure')['roi_id'] == \
        f'{BIN_ID}_00001'


def test_blobs_roi_coverage(tmp_path):
    write_blobs(tmp_path, clean_blob_members(targets=(1,)))
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    coverage = detail_for(report, 'blobs_roi_coverage')
    assert (coverage['covered'], coverage['total']) == (1, 3)


def test_blobs_container_corrupt(tmp_path):
    path = tmp_path / f'{BIN_ID}_blobs_v4.zip'
    path.write_bytes(b'PK\x03\x04 truncated')
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'product_container_corrupt')['product'] == 'blobs'


# --- class scores ---

def test_clean_class_scores_report_nothing(tmp_path):
    write_class_scores(tmp_path)
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert report.findings == []


def test_class_missing_dataset(tmp_path):
    write_class_scores(tmp_path, omit=('class_labels',))
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'class_missing_dataset')['dataset'] == 'class_labels'


def test_class_shape_mismatch(tmp_path):
    write_class_scores(tmp_path, labels=('a', 'b', 'c'))
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    mismatch = detail_for(report, 'class_shape_mismatch')
    assert mismatch['n_labels'] == 3
    assert mismatch['scores_shape'] == '3x2'


def test_class_bad_values(tmp_path):
    write_class_scores(tmp_path, scores=[
        [0.5, 0.5], [float('nan'), 0.5], [0.5, 0.5]])
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    bad = detail_for(report, 'class_bad_values')
    assert (bad['count'], bad['example']) == (1, 2)


def test_class_roi_mismatch(tmp_path):
    write_class_scores(tmp_path, roi_numbers=(1, 2))
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert detail_for(report, 'class_roi_mismatch')['covered'] == 2


def test_class_checks_are_skipped_without_h5py(tmp_path, monkeypatch):
    pytest.importorskip('h5py')
    write_class_scores(tmp_path)
    import builtins

    real_import = builtins.__import__

    def no_h5py(name, *args, **kwargs):
        if name == 'h5py':
            raise ImportError('h5py is not installed')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', no_h5py)
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert report.skipped['class_bad_values'] == 'h5py is not installed'
    assert report.findings == []


# --- the invariant that keeps the tolerant and strict readers in step ---

def test_clean_products_do_not_raise_in_the_strict_readers(tmp_path):
    features = write_features(tmp_path, clean_feature_rows())
    blobs = write_blobs(tmp_path, clean_blob_members())
    report = check_products(tmp_path, BIN_ID, targets=TARGETS)
    assert report.errors == []

    assert len(read_features(features)) == len(TARGETS)
    assert len(list(read_blobs(blobs))) == len(TARGETS)


@pytest.mark.parametrize('rows', [
    [('', 100, 200.5)],               # features_empty_roi_number
    [(1, 'wide', 200.5)],             # features_non_numeric
])
def test_files_qc_rejects_also_break_the_strict_reader(tmp_path, rows):
    features = write_features(tmp_path, rows)
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    assert report.errors, 'QC must flag what the strict reader cannot read'
    with pytest.raises(ValueError):
        read_features(features)


def test_qc_reports_a_ragged_row_the_strict_reader_silently_pads(tmp_path):
    # csv.DictReader fills missing fields with None, so read_features returns a
    # row with fewer features rather than raising. QC says the row is ragged.
    features = write_features(tmp_path, [(1, 100)])
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    assert 'features_ragged_rows' in codes(report)
    assert read_features(features) == [(1, {'Area': 100})]


def test_a_truncated_png_is_reported_and_fails_to_decode(tmp_path):
    truncated = png_bytes()[:20]
    blobs = write_blobs(tmp_path, [(f'{BIN_ID}_00001.png', truncated)])
    report = check_products(tmp_path, BIN_ID, targets=(1,))
    assert 'blobs_png_decode_failure' in codes(report)

    roi_id, data = next(iter(read_blobs(blobs)))
    with pytest.raises(Exception):
        Image.open(io.BytesIO(data)).load()


def test_finding_cap_counts_rather_than_floods(tmp_path):
    write_features(tmp_path, [(i, 'wide', 1) for i in range(1, 201)])
    report = check_products(tmp_path, BIN_ID, targets=tuple(range(1, 201)))
    assert len([f for f in report.findings if f.code == 'features_non_numeric']) \
        == report.max_per_code
    assert report.truncated['features_non_numeric'] == 200 - report.max_per_code
    assert report.total_for('features_non_numeric') == 200
