"""The ADC diagnostics channel: what the one parse path discarded, and why.

The contract these tests pin down is that ``diagnostics=None`` changes nothing
(``tests/test_characterization.py`` covers the well-formed case byte for byte)
and that with a channel supplied, every input line is accounted for exactly
once — either as a yielded target or as one diagnostic.
"""

import pytest

from ifcbkit.adc import (
    BLANK_LINE,
    SHORT_ROW,
    UNPARSEABLE,
    ZERO_GEOMETRY,
    iter_adc_targets,
)

D_BIN_ID = 'D20130526T095207_IFCB013'
I_BIN_ID = 'IFCB5_2012_028_081515'

# D-style: x/y/w/h at 13-16, offset at 17. 18 fields is the minimum.
def _d_line(trigger, x=10, y=20, width=30, height=40, offset=1000):
    fields = [str(trigger)] + ['0'] * 12 + [
        str(x), str(y), str(width), str(height), str(offset)]
    return ','.join(fields)


def _adc(*lines):
    return ('\n'.join(lines) + '\n').encode('utf-8')


def test_default_none_yields_the_same_targets(d_adc_bytes):
    without = list(iter_adc_targets(D_BIN_ID, d_adc_bytes))
    diagnostics = []
    with_channel = list(
        iter_adc_targets(D_BIN_ID, d_adc_bytes, diagnostics=diagnostics))
    assert with_channel == without


def test_real_bins_have_only_zero_geometry_skips(d_adc_bytes, i_adc_bytes):
    for bin_id, adc_bytes in ((D_BIN_ID, d_adc_bytes), (I_BIN_ID, i_adc_bytes)):
        diagnostics = []
        list(iter_adc_targets(bin_id, adc_bytes, diagnostics=diagnostics))
        assert {d['reason'] for d in diagnostics} <= {ZERO_GEOMETRY}


@pytest.mark.parametrize('bin_id, adc_bytes_fixture', [
    (D_BIN_ID, 'd_adc_bytes'),
    (I_BIN_ID, 'i_adc_bytes'),
])
def test_every_line_is_accounted_for_exactly_once(
        bin_id, adc_bytes_fixture, request):
    adc_bytes = request.getfixturevalue(adc_bytes_fixture)
    diagnostics = []
    targets = list(iter_adc_targets(bin_id, adc_bytes, diagnostics=diagnostics))

    n_lines = len(adc_bytes.decode('utf-8', errors='replace').splitlines())
    yielded = {t['target'] for t in targets}
    skipped = {d['line'] for d in diagnostics}
    assert not yielded & skipped
    assert yielded | skipped == set(range(1, n_lines + 1))


def test_blank_line_reason():
    adc = _adc(_d_line(1), '', _d_line(3))
    diagnostics = []
    targets = list(iter_adc_targets(D_BIN_ID, adc, diagnostics=diagnostics))

    assert [d['reason'] for d in diagnostics] == [BLANK_LINE]
    assert diagnostics[0]['line'] == 2
    # The blank line consumes target number 2, so the third line is target 3:
    # this is exactly the target-shifting the adc_blank_line check reports.
    assert [t['target'] for t in targets] == [1, 3]


def test_short_row_reason():
    adc = _adc(_d_line(1), '5,6,7')
    diagnostics = []
    list(iter_adc_targets(D_BIN_ID, adc, diagnostics=diagnostics))
    assert diagnostics == [{
        'line': 2, 'reason': SHORT_ROW, 'text': '5,6,7', 'n_fields': 3}]


def test_unparseable_reason():
    bad = _d_line(2, width='wide')
    adc = _adc(_d_line(1), bad)
    diagnostics = []
    list(iter_adc_targets(D_BIN_ID, adc, diagnostics=diagnostics))
    assert diagnostics[0]['reason'] == UNPARSEABLE
    assert diagnostics[0]['text'] == bad
    assert diagnostics[0]['n_fields'] == 18


def test_zero_geometry_reason():
    adc = _adc(_d_line(1), _d_line(2, width=0), _d_line(3, height=0))
    diagnostics = []
    targets = list(iter_adc_targets(D_BIN_ID, adc, diagnostics=diagnostics))
    assert [d['reason'] for d in diagnostics] == [ZERO_GEOMETRY, ZERO_GEOMETRY]
    assert [d['line'] for d in diagnostics] == [2, 3]
    assert [t['target'] for t in targets] == [1]


def test_unparseable_trigger_is_a_skip_not_a_partial_record():
    # The refactor made trigger and offset required for a usable target; this
    # is the property that keeps ADC parsing and ROI extraction in agreement.
    adc = _adc('notatrigger' + _d_line(0)[1:])
    diagnostics = []
    targets = list(iter_adc_targets(D_BIN_ID, adc, diagnostics=diagnostics))
    assert targets == []
    assert diagnostics[0]['reason'] == UNPARSEABLE


def test_i_style_layout_is_used_for_i_style_bins():
    # I-style: x/y/w/h at 9-12, offset at 13 — a 14-field row is complete.
    fields = ['7'] + ['0'] * 8 + ['1', '2', '3', '4', '500']
    diagnostics = []
    targets = list(iter_adc_targets(
        I_BIN_ID, _adc(','.join(fields)), diagnostics=diagnostics))
    assert diagnostics == []
    assert targets[0]['width'] == 3
    assert targets[0]['offset'] == 500
