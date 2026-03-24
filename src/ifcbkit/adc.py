"""
IFCB ADC (.adc) file parsing.

ADC files are CSV with one line per trigger. Column indices differ between
I-style and D-style bin IDs:
- I-style: x/y/w/h at columns 9-12, offset at 13
- D-style: x/y/w/h at columns 13-16, offset at 17

Parsed into plain dicts, not DataFrames.
"""

from .identifiers import add_target


# Column index mappings by bin ID style
I_STYLE_COLUMNS = {
    'x': 9, 'y': 10, 'width': 11, 'height': 12, 'offset': 13,
}
D_STYLE_COLUMNS = {
    'x': 13, 'y': 14, 'width': 15, 'height': 16, 'offset': 17,
}


def _columns_for_bin_id(bin_id: str) -> dict:
    """Return the column index mapping for the given bin ID style."""
    if bin_id.startswith('I'):
        return I_STYLE_COLUMNS
    return D_STYLE_COLUMNS


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
    cols = _columns_for_bin_id(bin_id)
    x_col, y_col = cols['x'], cols['y']
    w_col, h_col = cols['width'], cols['height']
    offset_col = cols['offset']

    images = {}
    for i, line in enumerate(adc_bytes.decode('utf-8', errors='replace').splitlines()):
        fields = line.strip().split(',')
        try:
            x = int(fields[x_col])
            y = int(fields[y_col])
            width = int(fields[w_col])
            height = int(fields[h_col])
        except (ValueError, IndexError):
            continue
        if width == 0 or height == 0:
            continue
        entry = {
            'roi_id': add_target(bin_id, i + 1),
            'x': x,
            'y': y,
            'width': width,
            'height': height,
        }
        if extended:
            try:
                entry['trigger'] = int(fields[0])
                entry['offset'] = int(fields[offset_col])
            except (ValueError, IndexError):
                pass
        images[i + 1] = entry
    return images


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
    :returns: dict with roi_id, x, y, width, height, offset; or None
    """
    cols = _columns_for_bin_id(bin_id)
    fields = line.strip().split(',')
    try:
        x = int(fields[cols['x']])
        y = int(fields[cols['y']])
        width = int(fields[cols['width']])
        height = int(fields[cols['height']])
        offset = int(fields[cols['offset']])
    except (ValueError, IndexError):
        return None
    if width == 0 or height == 0:
        return None
    return {
        'roi_id': add_target(bin_id, line_index + 1),
        'target': line_index + 1,
        'x': x,
        'y': y,
        'width': width,
        'height': height,
        'offset': offset,
    }
