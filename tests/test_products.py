from zipfile import ZipFile

import pytest

from ifcbkit import (
    ClassScoresRows,
    read_blobs,
    read_class_scores,
    read_features,
    sync_blob_path,
    sync_class_scores_path,
    sync_features_path,
)


def test_sync_features_path_uses_real_filename(tmp_path):
    path = tmp_path / "D20250101T020023_IFCB010_fea_v4.csv"
    path.write_text("roi_number,Area\n1,2\n")

    found = sync_features_path(tmp_path, "D20250101T020023_IFCB010")

    assert found == str(path)


def test_sync_class_scores_path_uses_real_filename(tmp_path):
    path = tmp_path / "D20250101T020023_IFCB010_class.h5"
    path.write_bytes(b"")

    found = sync_class_scores_path(tmp_path, "D20250101T020023_IFCB010")

    assert found == str(path)


def test_sync_blob_path_uses_real_filename(tmp_path):
    path = tmp_path / "D20250101T020023_IFCB010_blobs_v4.zip"
    path.write_bytes(b"")

    found = sync_blob_path(tmp_path, "D20250101T020023_IFCB010")

    assert found == str(path)


def test_read_features_returns_roi_number_and_scalar_dict(tmp_path):
    path = tmp_path / "features.csv"
    path.write_text(
        "roi_number,Area,Count,MajorAxisLength\n"
        "2,1.5,3,4.25\n"
        "5,2.0,4,6.5\n"
    )

    rows = read_features(path)

    assert rows == [
        (2, {"Area": 1.5, "Count": 3, "MajorAxisLength": 4.25}),
        (5, {"Area": 2.0, "Count": 4, "MajorAxisLength": 6.5}),
    ]


def test_read_features_accepts_roi_number_camel_case(tmp_path):
    path = tmp_path / "features.csv"
    path.write_text(
        "roiNumber,Area,Count\n"
        "7,1.5,3\n"
    )

    rows = read_features(path)

    assert rows == [(7, {"Area": 1.5, "Count": 3})]


def test_read_blobs_yields_roi_id_and_png_bytes(tmp_path):
    path = tmp_path / "blobs.zip"
    with ZipFile(path, "w") as zf:
        zf.writestr("D20250101T020023_IFCB010_00002.png", b"png-a")
        zf.writestr("nested/D20250101T020023_IFCB010_00003.png", b"png-b")
        zf.writestr("ignore.txt", b"nope")

    rows = list(read_blobs(path))

    assert rows == [
        ("D20250101T020023_IFCB010_00002", b"png-a"),
        ("D20250101T020023_IFCB010_00003", b"png-b"),
    ]


def test_read_class_scores_returns_class_names_and_rows(tmp_path):
    h5py = pytest.importorskip("h5py")

    path = tmp_path / "scores.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("output_scores", data=[[0.1, 0.9], [0.8, 0.2]])
        handle.create_dataset("class_labels", data=[b"detritus", b"diatom"])
        handle.create_dataset("roi_numbers", data=[2, 5])

    result = read_class_scores(path)

    assert isinstance(result, ClassScoresRows)
    assert result.class_names == ["detritus", "diatom"]
    assert result.rows == [
        (2, {"detritus": 0.1, "diatom": 0.9}),
        (5, {"detritus": 0.8, "diatom": 0.2}),
    ]
