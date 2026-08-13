"""
IFCB ADC (.adc) file parsing.

ADC files are CSV with one line per trigger. Column indices differ between
I-style and D-style bin IDs:
- I-style: x/y/w/h at columns 9-12, offset at 13
- D-style: x/y/w/h at columns 13-16, offset at 17

``iter_adc_targets`` is the single ADC parse path in ifcbkit. Everything else
that reads ADC data — the functions below, ``roi.extract_roi_images``,
``stitching.bin_images``, and the data directory classes — is a projection or
filter of what it yields. Keeping one implementation is what lets the library
give one answer to "is this line malformed".

Parsed into plain dicts, not DataFrames.
"""

from collections.abc import Iterator

from .identifiers import add_target


# Column index mappings by bin ID style
I_STYLE_COLUMNS = {
    'x': 9, 'y': 10, 'width': 11, 'height': 12, 'offset': 13,
}
D_STYLE_COLUMNS = {
    'x': 13, 'y': 14, 'width': 15, 'height': 16, 'offset': 17,
}

# Key sets of the public projections, preserved exactly as they were before
# these functions were unified onto a single parse path.
_PLAIN_KEYS = ('roi_id', 'x', 'y', 'width', 'height')
_EXTENDED_KEYS = _PLAIN_KEYS + ('trigger', 'offset')
_LINE_KEYS = ('roi_id', 'target', 'x', 'y', 'width', 'height', 'offset')


def _columns_for_bin_id(bin_id: str) -> dict:
    """Return the column index mapping for the given bin ID style."""
    if bin_id.startswith('I'):
        return I_STYLE_COLUMNS
    return D_STYLE_COLUMNS


def _project(record: dict, keys) -> dict:
    """Narrow a full target record to one of the public key sets."""
    return {k: record[k] for k in keys}


def _parse_fields(bin_id: str, cols: dict, fields: list, line_index: int) -> dict | None:
    """Parse split ADC fields into a full target record, or None if unusable.

    A line is usable only if the trigger, geometry, and offset columns all
    parse as integers and the ROI has non-zero area. Requiring the offset here
    is what guarantees that ADC parsing and ROI extraction agree on which
    targets exist.

    :param bin_id: the bin ID string
    :param cols: column index mapping from :func:`_columns_for_bin_id`
    :param fields: the comma-split fields of one ADC line
    :param line_index: 0-based line index
    :returns: dict with target, roi_id, trigger, x, y, width, height, offset;
      or None
    """
    try:
        record = {
            'target': line_index + 1,
            'roi_id': add_target(bin_id, line_index + 1),
            'trigger': int(fields[0]),
            'x': int(fields[cols['x']]),
            'y': int(fields[cols['y']]),
            'width': int(fields[cols['width']]),
            'height': int(fields[cols['height']]),
            'offset': int(fields[cols['offset']]),
        }
    except (ValueError, IndexError):
        return None
    if record['width'] == 0 or record['height'] == 0:
        return None
    return record


def iter_adc_targets(bin_id: str, adc_bytes: bytes) -> Iterator[dict]:
    """Yield a full record for each ADC line describing a usable ROI.

    The single ADC parse path. Lines with no ROI (zero width or height) and
    lines that do not parse are both skipped; distinguishing the two is the
    job of a QC layer built on this function, not of this function.

    :param bin_id: the bin ID string (needed to determine column layout)
    :param adc_bytes: raw bytes of the .adc file
    :returns: iterator of dicts with target, roi_id, trigger, x, y, width,
      height, offset
    """
    cols = _columns_for_bin_id(bin_id)
    text = adc_bytes.decode('utf-8', errors='replace')
    for i, line in enumerate(text.splitlines()):
        record = _parse_fields(bin_id, cols, line.strip().split(','), i)
        if record is not None:
            yield record


def parse_adc_bytes(bin_id: str, adc_bytes: bytes, *, extended: bool = False) -> dict:
    """Parse .adc CSV bytes into ROI metadata dict.

    Returns a dict mapping target number (1-based) to a dict with
    roi_id, x, y, width, height for each trigger that has a non-zero ROI.

    When extended=True, each dict also includes 'trigger' (column 0) and
    'offset' (byte offset into .roi file), needed for stitching.

    :param bin_id: the bin ID string (needed to determine column layout)
    :param adc_bytes: raw bytes of the .adc file
    :param extended: if True, include trigger and offset in output
    :returns: dict of {target_number: {roi_id, x, y, width, height, ...}}
    """
    keys = _EXTENDED_KEYS if extended else _PLAIN_KEYS
    return {
        record['target']: _project(record, keys)
        for record in iter_adc_targets(bin_id, adc_bytes)
    }


def parse_adc_file(bin_id: str, adc_path: str, *, extended: bool = False) -> dict:
    """Parse an .adc file from a filesystem path.

    :param bin_id: the bin ID string
    :param adc_path: path to the .adc file
    :param extended: if True, include trigger and offset in output
    :returns: dict of {target_number: {roi_id, x, y, width, height, ...}}
    """
    with open(adc_path, 'rb') as f:
        return parse_adc_bytes(bin_id, f.read(), extended=extended)


def parse_adc_line(bin_id: str, line: str, line_index: int) -> dict | None:
    """Parse a single ADC line into ROI metadata, or None if no ROI.

    :param bin_id: the bin ID string
    :param line: a single line from the .adc file
    :param line_index: 0-based line index
    :returns: dict with roi_id, target, x, y, width, height, offset; or None
    """
    cols = _columns_for_bin_id(bin_id)
    record = _parse_fields(bin_id, cols, line.strip().split(','), line_index)
    if record is None:
        return None
    return _project(record, _LINE_KEYS)
