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

# Reasons a line yields no target. Reported through the optional diagnostics
# channel; consumers map them to their own vocabulary (ifcbkit.qc does).
BLANK_LINE = 'blank_line'
SHORT_ROW = 'short_row'
UNPARSEABLE = 'unparseable'
ZERO_GEOMETRY = 'zero_geometry'
SKIP_REASONS = (BLANK_LINE, SHORT_ROW, UNPARSEABLE, ZERO_GEOMETRY)

# Field names that D-style headers use for the columns ifcbkit reads, in
# ADCFileFormat declarations. Compared case- and separator-insensitively.
_DECLARED_FIELD_ALIASES = {
    'x': ('roix',),
    'y': ('roiy',),
    'width': ('roiwidth',),
    'height': ('roiheight',),
    'offset': ('startbyte', 'startbyte#', 'roistartbyte'),
}


def columns_for_bin_id(bin_id: str) -> dict:
    """Return the column index mapping for the given bin ID style.

    :param bin_id: the bin ID string
    :returns: :data:`I_STYLE_COLUMNS` or :data:`D_STYLE_COLUMNS` itself, not a
      copy — callers may compare identity
    """
    if bin_id.startswith('I'):
        return I_STYLE_COLUMNS
    return D_STYLE_COLUMNS


def _project(record: dict, keys) -> dict:
    """Narrow a full target record to one of the public key sets."""
    return {k: record[k] for k in keys}


def _parse_fields_detail(
    bin_id: str, cols: dict, fields: list, line_index: int,
) -> tuple[dict | None, str | None]:
    """Parse split ADC fields, reporting *why* a line is unusable.

    A line is usable only if the trigger, geometry, and offset columns all
    parse as integers and the ROI has non-zero area. Requiring the offset here
    is what guarantees that ADC parsing and ROI extraction agree on which
    targets exist.

    :param bin_id: the bin ID string
    :param cols: column index mapping from :func:`columns_for_bin_id`
    :param fields: the comma-split fields of one ADC line
    :param line_index: 0-based line index
    :returns: ``(record, None)`` for a usable line, else ``(None, reason)``
      where reason is one of ``blank_line``, ``short_row``, ``unparseable``,
      ``zero_geometry``
    """
    if fields == ['']:
        return None, BLANK_LINE
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
    except IndexError:
        return None, SHORT_ROW
    except ValueError:
        return None, UNPARSEABLE
    if record['width'] == 0 or record['height'] == 0:
        return None, ZERO_GEOMETRY
    return record, None


def _parse_fields(bin_id: str, cols: dict, fields: list, line_index: int) -> dict | None:
    """Parse split ADC fields into a full target record, or None if unusable.

    Thin wrapper over :func:`_parse_fields_detail` for callers that do not
    care why a line was rejected.

    :param bin_id: the bin ID string
    :param cols: column index mapping from :func:`columns_for_bin_id`
    :param fields: the comma-split fields of one ADC line
    :param line_index: 0-based line index
    :returns: dict with target, roi_id, trigger, x, y, width, height, offset;
      or None
    """
    record, _ = _parse_fields_detail(bin_id, cols, fields, line_index)
    return record


def iter_adc_targets(bin_id: str, adc_bytes: bytes, *, diagnostics=None) -> Iterator[dict]:
    """Yield a full record for each ADC line describing a usable ROI.

    The single ADC parse path. Lines with no ROI (zero width or height) and
    lines that do not parse are both skipped. Pass ``diagnostics`` to find out
    which lines those were and why — that channel is what lets a QC layer
    report on ADC integrity without a second parse that could disagree with
    this one.

    :param bin_id: the bin ID string (needed to determine column layout)
    :param adc_bytes: raw bytes of the .adc file
    :param diagnostics: optional list; one dict is appended per skipped line,
      with keys ``line`` (1-based, equal to the target number that line would
      have had), ``reason``, ``text``, and ``n_fields``. Default ``None``
      appends nothing and costs nothing.
    :returns: iterator of dicts with target, roi_id, trigger, x, y, width,
      height, offset
    """
    cols = columns_for_bin_id(bin_id)
    text = adc_bytes.decode('utf-8', errors='replace')
    for i, line in enumerate(text.splitlines()):
        fields = line.strip().split(',')
        record, reason = _parse_fields_detail(bin_id, cols, fields, i)
        if record is not None:
            yield record
        elif diagnostics is not None:
            diagnostics.append({
                'line': i + 1,
                'reason': reason,
                'text': line,
                'n_fields': len(fields),
            })


def columns_from_declaration(field_names) -> dict | None:
    """Derive a column index mapping from declared ADC field names.

    D-style headers declare the ADC layout in an ``ADCFileFormat:`` key (see
    :func:`ifcbkit.header.parse_adc_file_format`). This turns those names into
    the same mapping shape as :data:`I_STYLE_COLUMNS`, so a QC check can
    compare what the file *says* its layout is against the layout ifcbkit
    picks from the bin ID style.

    :param field_names: declared field names, in file order
    :returns: mapping with x, y, width, height, offset; or None if the
      declaration does not name all five
    """
    lowered = [name.strip().lower().replace('_', '').replace(' ', '')
               for name in field_names]
    cols = {}
    for key, aliases in _DECLARED_FIELD_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                cols[key] = lowered.index(alias)
                break
        else:
            return None
    return cols


def targets_to_dict(targets, *, extended: bool = False) -> dict:
    """Convert target records into the metadata dict shape.

    The companion to :func:`iter_adc_targets`: use it when you already have
    the target records and also need the dict that :func:`parse_adc_bytes`
    returns, instead of parsing the ADC a second time.

    :param targets: iterable of records from :func:`iter_adc_targets`
    :param extended: if True, include trigger and offset in output
    :returns: dict of {target_number: {roi_id, x, y, width, height, ...}}
    """
    keys = _EXTENDED_KEYS if extended else _PLAIN_KEYS
    return {record['target']: _project(record, keys) for record in targets}


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
    return targets_to_dict(
        iter_adc_targets(bin_id, adc_bytes), extended=extended)


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
    cols = columns_for_bin_id(bin_id)
    record = _parse_fields(bin_id, cols, line.strip().split(','), line_index)
    if record is None:
        return None
    return _project(record, _LINE_KEYS)
