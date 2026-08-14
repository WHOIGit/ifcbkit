"""The header diagnostics channel, and the ADCFileFormat declaration parser."""

from ifcbkit.adc import D_STYLE_COLUMNS, columns_from_declaration
from ifcbkit.header import (
    ADC_FILE_FORMAT,
    CAST_FAILURE,
    COLUMN_COUNT_MISMATCH,
    MISSING_KEYS,
    TRUNCATED,
    UNRECOGNIZED_FORMAT,
    V2_BANNER,
    parse_adc_file_format,
    parse_hdr,
    parse_hdr_file,
)

COLUMNS_ROW = '"Temp Humidity BinarizeThresh PMT1hv(ssc) PMT2hv(chl) BlobSizeThresh"'
CONTEXT_ROWS = ['"ctx one"', '"ctx two"', '"ctx three"', '"SyringeStatus =  0"']


def _legacy(values_row, columns_row=COLUMNS_ROW):
    return CONTEXT_ROWS + [columns_row, values_row]


def _reasons(diagnostics):
    return [d['reason'] for d in diagnostics]


def test_real_headers_produce_no_diagnostics(d_hdr_path, i_hdr_path):
    for path in (d_hdr_path, i_hdr_path):
        diagnostics = []
        props = parse_hdr_file(path, diagnostics=diagnostics)
        assert diagnostics == [], path
        assert props


def test_default_none_yields_the_same_props(i_hdr_path):
    assert parse_hdr_file(i_hdr_path) == \
        parse_hdr_file(i_hdr_path, diagnostics=[])


def test_v2_banner_alone_is_truncated_not_an_indexerror():
    diagnostics = []
    props = parse_hdr([V2_BANNER], diagnostics=diagnostics)
    assert _reasons(diagnostics) == [TRUNCATED]
    assert diagnostics[0]['n_lines'] == 1
    assert props == {'context': V2_BANNER}


def test_v2_banner_without_sample_date_is_unrecognized():
    diagnostics = []
    parse_hdr([V2_BANNER, 'something else entirely'], diagnostics=diagnostics)
    assert _reasons(diagnostics) == [UNRECOGNIZED_FORMAT]
    assert diagnostics[0]['context'] == V2_BANNER


def test_alt_format_is_recognized():
    diagnostics = []
    props = parse_hdr([
        V2_BANNER,
        'Sample Date 26 May 2013',
        'run time = 1.25 s  inhibit time = 0.50',
        '11.5 temperature, 32.0 humidity',
    ], diagnostics=diagnostics)
    assert diagnostics == []
    assert props['runTime'] == 1.25
    assert props['temperature'] == 11.5


def test_legacy_format_clean():
    diagnostics = []
    props = parse_hdr(
        _legacy('" 11.5"," 32.1"," 30"," .675"," .6"," 10"'),
        diagnostics=diagnostics)
    assert diagnostics == []
    assert props['temperature'] == 11.5
    assert props['blobSizeThreshold'] == 10


def test_cast_failure_keeps_the_raw_value():
    diagnostics = []
    props = parse_hdr(
        _legacy('" hot"," 32.1"," 30"," .675"," .6"," 10"'),
        diagnostics=diagnostics)
    assert _reasons(diagnostics) == [CAST_FAILURE]
    assert diagnostics[0]['key'] == 'temperature'
    assert diagnostics[0]['type_name'] == 'float'
    # Not raised, and not dropped: one bad field does not cost the whole header.
    assert props['temperature'] == 'hot'
    assert props['humidity'] == 32.1


def test_column_count_mismatch_is_reported():
    diagnostics = []
    parse_hdr(
        _legacy('" 11.5"," 32.1"," 30"," .675"," .6"," 10"',
                columns_row='"Temp Humidity BinarizeThresh PMT1hv(ssc) PMT2hv(chl)"'),
        diagnostics=diagnostics)
    assert COLUMN_COUNT_MISMATCH in _reasons(diagnostics)
    entry = next(d for d in diagnostics if d['reason'] == COLUMN_COUNT_MISMATCH)
    assert (entry['n_columns'], entry['n_values']) == (5, 6)


def test_short_value_row_reports_missing_keys():
    diagnostics = []
    props = parse_hdr(
        _legacy('" 11.5"," 32.1"," 30"," .675"'), diagnostics=diagnostics)
    assert MISSING_KEYS in _reasons(diagnostics)
    entry = next(d for d in diagnostics if d['reason'] == MISSING_KEYS)
    assert entry['missing'] == [
        'fluorescencePhotomultiplierSetting', 'blobSizeThreshold']
    assert 'blobSizeThreshold' not in props


def test_parse_adc_file_format_splits_declared_names(d_hdr_path):
    props = parse_hdr_file(d_hdr_path)
    names = parse_adc_file_format(props[ADC_FILE_FORMAT])
    assert names[0] == 'trigger#'
    assert 'ROIwidth' in names
    assert parse_adc_file_format('') == []


def test_declared_layout_matches_the_d_style_layout(d_hdr_path):
    props = parse_hdr_file(d_hdr_path)
    names = parse_adc_file_format(props[ADC_FILE_FORMAT])
    assert columns_from_declaration(names) == D_STYLE_COLUMNS


def test_declaration_without_all_five_columns_is_unusable():
    assert columns_from_declaration(['trigger#', 'ROIx', 'ROIy']) is None
