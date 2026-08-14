"""Checks on corrected ADC files (.adc.mod), the adcmod group.

Layout, per :func:`ifcbkit.fileset.adcmod_path`: the ``adcmod`` directory is a
sibling of the raw data root, holding ``<day>/<pid>.adc.mod``.
"""

import os

from ifcbkit.qc import Cost, Severity
from ifcbkit.qc.raw import check_fileset

from .fixtures import (
    D_BIN_ID,
    copy_fileset,
    read_adc_lines,
    remove_file,
    target_line_numbers,
)


def codes(report):
    return report.counts_by_code()


def _raw_tree(tmp_path, day='D20130526'):
    """Build ``<tmp>/data/<day>/<bin>.*`` and return (root_path, basepath)."""
    root = tmp_path / 'data'
    basepath = copy_fileset(root, D_BIN_ID, into=day)
    return str(root), basepath


def _write_mod(tmp_path, day, lines, bin_id=D_BIN_ID):
    """Write ``<tmp>/adcmod/<day>/<bin>.adc.mod`` and return its path."""
    directory = tmp_path / 'adcmod' / day
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'{bin_id}.adc.mod'
    path.write_text('\n'.join(lines) + '\n')
    return str(path)


def test_no_adcmod_tree_means_no_adcmod_findings(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    report = check_fileset(basepath, cost=Cost.PARSE, root_path=root_path)
    assert not any(f.code.startswith('adcmod') for f in report.findings)


def test_identical_correction_reports_nothing(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    _write_mod(tmp_path, 'D20130526', read_adc_lines(basepath))
    report = check_fileset(basepath, cost=Cost.PARSE, root_path=root_path)
    assert not any(f.code.startswith('adcmod') for f in report.findings)
    assert report.ok


def test_adcmod_row_delta_is_info(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    lines = read_adc_lines(basepath)
    dropped = target_line_numbers(basepath)[0]
    del lines[dropped - 1]
    _write_mod(tmp_path, 'D20130526', lines)

    report = check_fileset(basepath, cost=Cost.PARSE, root_path=root_path)
    delta = next(f for f in report.findings if f.code == 'adcmod_row_delta')
    assert delta.severity is Severity.INFO
    assert delta.detail['raw_count'] - delta.detail['mod_count'] == 1
    assert report.ok


def test_adcmod_geometry_delta_is_info(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    lines = read_adc_lines(basepath)
    number = target_line_numbers(basepath)[0]
    fields = lines[number - 1].split(',')
    fields[15] = str(int(fields[15]) + 2)  # D-style width
    lines[number - 1] = ','.join(fields)
    _write_mod(tmp_path, 'D20130526', lines)

    report = check_fileset(basepath, cost=Cost.PARSE, root_path=root_path)
    delta = next(f for f in report.findings if f.code == 'adcmod_geometry_delta')
    assert delta.severity is Severity.INFO
    assert delta.detail['count'] == 1


def test_adcmod_invalid_when_it_has_no_usable_targets(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    _write_mod(tmp_path, 'D20130526', ['not an adc file'])
    report = check_fileset(basepath, cost=Cost.PARSE, root_path=root_path)
    invalid = next(f for f in report.findings if f.code == 'adcmod_invalid')
    assert invalid.severity is Severity.ERROR
    assert not report.ok


def test_adcmod_orphan_when_the_raw_adc_is_gone(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    _write_mod(tmp_path, 'D20130526', read_adc_lines(basepath))
    remove_file(basepath, 'adc')
    report = check_fileset(basepath, cost=Cost.PARSE, root_path=root_path)
    orphan = next(f for f in report.findings if f.code == 'adcmod_orphan')
    assert orphan.severity is Severity.WARNING


def test_adcmod_orphan_is_reported_at_stat_cost(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    _write_mod(tmp_path, 'D20130526', read_adc_lines(basepath))
    remove_file(basepath, 'adc')
    report = check_fileset(basepath, cost=Cost.STAT, root_path=root_path)
    assert 'adcmod_orphan' in codes(report)


def test_explicit_adcmod_path_overrides_root_derivation(tmp_path):
    root_path, basepath = _raw_tree(tmp_path)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    path = elsewhere / f'{D_BIN_ID}.adc.mod'
    path.write_text('garbage\n')

    report = check_fileset(basepath, cost=Cost.PARSE, adcmod=str(path))
    invalid = next(f for f in report.findings if f.code == 'adcmod_invalid')
    assert invalid.path == str(path)
    assert os.path.exists(path)
