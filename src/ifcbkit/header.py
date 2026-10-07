"""
Support for parsing IFCB header (.hdr) files.

Handles multiple instrument software versions:
- Alt header format (Imaging FlowCytobot Acquisition Software v2.0)
- RFC 822-style SoftwareVersion: format
- Legacy metadata-column format

Extracts: temperature, humidity, binarizeThreshold, PMT settings,
blob size threshold. Automatic type casting via schema.
"""

import ast
import re

# hdr attributes (camel-case, mapped to column names below)
TEMPERATURE = 'temperature'
HUMIDITY = 'humidity'
BINARIZE_THRESHOLD = 'binarizeThreshold'
SCATTERING_PMT_SETTING = 'scatteringPhotomultiplierSetting'
FLUORESCENCE_PMT_SETTING = 'fluorescencePhotomultiplierSetting'
BLOB_SIZE_THRESHOLD = 'blobSizeThreshold'

# column name / type pairs
HDR_SCHEMA = [
    (TEMPERATURE, float),
    (HUMIDITY, float),
    (BINARIZE_THRESHOLD, int),
    (SCATTERING_PMT_SETTING, float),
    (FLUORESCENCE_PMT_SETTING, float),
    (BLOB_SIZE_THRESHOLD, int),
]

# hdr column names (metadata CSV header row)
HDR_COLUMNS = ['Temp', 'Humidity', 'BinarizeThresh', 'PMT1hv(ssc)', 'PMT2hv(chl)', 'BlobSizeThresh']

CONTEXT = 'context'

# The banner line that identifies the Acquisition Software v2.0 format.
V2_BANNER = 'Imaging FlowCytobot Acquisition Software version 2.0; May 2010'

# Header key whose value declares the ADC column layout (D-style instruments).
ADC_FILE_FORMAT = 'ADCFileFormat'

# Reasons a header is not fully understood. Reported through the optional
# diagnostics channel; ifcbkit.qc maps them to check codes.
UNRECOGNIZED_FORMAT = 'unrecognized_format'
TRUNCATED = 'truncated'
CAST_FAILURE = 'cast_failure'
COLUMN_COUNT_MISMATCH = 'column_count_mismatch'
MISSING_KEYS = 'missing_keys'
HDR_DIAGNOSTIC_REASONS = (
    UNRECOGNIZED_FORMAT, TRUNCATED, CAST_FAILURE, COLUMN_COUNT_MISMATCH,
    MISSING_KEYS,
)


def _diag(diagnostics, reason, **detail):
    """Append one diagnostic, if a channel was supplied."""
    if diagnostics is not None:
        diagnostics.append({'reason': reason, **detail})


def parse_adc_file_format(value: str) -> list:
    """Split an ``ADCFileFormat`` header value into declared field names.

    D-style headers declare their ADC column layout here. ifcbkit otherwise
    picks a layout from the bin ID style alone, so parsing this is what makes
    it possible to check the two against each other; see
    :func:`ifcbkit.adc.columns_from_declaration`.

    :param value: the raw ADCFileFormat value
    :returns: declared field names in file order (empty if there are none)
    """
    if not value:
        return []
    return [name.strip() for name in str(value).split(',') if name.strip()]


def _parse_alt_header(lines):
    """Parse the alternate header format (Acquisition Software v2.0)."""
    props = {}
    for line in lines:
        m = re.match(r'^run time = ([\d.]+) s\s+inhibit time = ([\d.]+)', line)
        if m:
            props['runTime'] = float(m.group(1))
            props['inhibitTime'] = float(m.group(2))
            continue
        m = re.match(r'([\d.]+) temperature,\s+([\d.]+) humidity', line)
        if m:
            props['temperature'] = float(m.group(1))
            props['humidity'] = float(m.group(2))
    return props


def parse_hdr(lines, *, diagnostics=None):
    """
    Given the lines of a header file, return the properties in it.

    :param lines: an iterable of strings, the lines of the file
    :param diagnostics: optional list; one dict is appended per aspect of the
      header that was not fully understood, with a ``reason`` key drawn from
      :data:`HDR_DIAGNOSTIC_REASONS` plus reason-specific detail. Default
      ``None`` appends nothing. Values that fail their schema cast are left
      as the raw string rather than raising.
    :returns: dict of header properties
    """
    lines = [line.rstrip() for line in lines]
    if not lines:
        return {}
    if lines[0] == V2_BANNER:
        if len(lines) < 2:
            _diag(diagnostics, TRUNCATED, n_lines=len(lines),
                  format_name='Acquisition Software v2.0')
            return {CONTEXT: lines[0]}
        if lines[1].startswith('Sample Date'):
            return _parse_alt_header(lines)
        _diag(diagnostics, UNRECOGNIZED_FORMAT, context=lines[0])
        props = {CONTEXT: lines[0]}  # FIXME parse
    elif re.match(r'^[Ss]oftwareVersion:', lines[0]):
        props = {CONTEXT: lines[0]}
        for line in lines[1:]:
            try:
                k, v = re.split(r': ', line)
                try:
                    v = ast.literal_eval(v)
                except (ValueError, SyntaxError):
                    pass
                props[k] = v
            except ValueError:
                # not valid RFC 822. Ignore.
                pass
    else:
        # "context" is what the text on lines 2-4 is called in the header file
        props = {CONTEXT: '\n'.join([line.strip('"') for line in lines[:-2]])}
        # now handle format variants
        if len(lines) >= 6:  # don't fail on original header format
            columns = re.split(' +', re.sub('"', '', lines[-2]))
            values = re.split(' +', re.sub(r'[",]', ' ', lines[-1]).strip())
            # Values are assigned to HDR_SCHEMA names positionally, so a
            # column row that does not line up with the value row silently
            # mis-assigns every value from that point on.
            if len(columns) != len(values):
                _diag(diagnostics, COLUMN_COUNT_MISMATCH,
                      n_columns=len(columns), n_values=len(values),
                      columns=columns)
            if len(values) < len(HDR_COLUMNS):
                _diag(diagnostics, MISSING_KEYS,
                      missing=[name for name, _ in HDR_SCHEMA[len(values):]],
                      n_values=len(values))
            for (column, (name, _), value) in zip(HDR_COLUMNS, HDR_SCHEMA, values):
                props[name] = value
    # cast any properties we know about in the schema
    for name, cast in HDR_SCHEMA:
        if name in props:
            try:
                props[name] = cast(props[name])
            except (TypeError, ValueError) as e:
                # Leave the raw value in place: a header with one bad field is
                # still worth reading, and QC is what reports the bad field.
                _diag(diagnostics, CAST_FAILURE, key=name,
                      value=props[name], type_name=cast.__name__, error=str(e))
    return props


def parse_hdr_file(path, *, diagnostics=None):
    """
    Given a path to a header file, return the header properties.

    :param path: a pathname
    :param diagnostics: optional list, passed through to :func:`parse_hdr`
    :returns: dict of header properties
    """
    with open(path, 'r') as f:
        lines = f.readlines()
    return parse_hdr(lines, diagnostics=diagnostics)


def parse_hdr_bytes(content: bytes, *, diagnostics=None) -> dict:
    """
    Given the bytes of a header file, return the header properties.

    :param content: bytes of the header file
    :param diagnostics: optional list, passed through to :func:`parse_hdr`
    :returns: dict of header properties
    """
    lines = content.decode('utf-8', errors='replace').splitlines()
    return parse_hdr(lines, diagnostics=diagnostics)
