"""Factories that build damaged filesets from the two real committed bins.

Every QC check needs an input that triggers it. Rather than commit more binary
test data, each factory copies a real fileset into ``tmp_path`` and breaks one
specific thing, so the rest of the bin stays realistic.
"""

import os
import shutil

from ifcbkit.adc import D_STYLE_COLUMNS, I_STYLE_COLUMNS

D_BIN_ID = 'D20130526T095207_IFCB013'
I_BIN_ID = 'IFCB5_2012_028_081515'
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

EXTENSIONS = ('hdr', 'adc', 'roi')


def columns_for(bin_id):
    """Return the ADC column mapping for a bin ID style."""
    return I_STYLE_COLUMNS if bin_id.startswith('I') else D_STYLE_COLUMNS


def copy_fileset(tmp_path, bin_id=D_BIN_ID, *, into=None, new_bin_id=None):
    """Copy a real fileset into tmp_path and return its basepath.

    :param tmp_path: pytest tmp_path
    :param bin_id: which committed bin to copy
    :param into: subdirectory name to copy into (default: the bin ID)
    :param new_bin_id: rename the copy to this bin ID
    :returns: the basepath of the copy (no extension)
    """
    target_id = new_bin_id or bin_id
    directory = tmp_path / (into if into is not None else target_id)
    directory.mkdir(parents=True, exist_ok=True)
    for ext in EXTENSIONS:
        shutil.copy(
            os.path.join(DATA_DIR, bin_id, f'{bin_id}.{ext}'),
            directory / f'{target_id}.{ext}')
    return str(directory / target_id)


def read_adc_lines(basepath):
    """Return the .adc lines of a fileset copy as a list of strings."""
    with open(basepath + '.adc', 'r') as f:
        return f.read().splitlines()


def write_adc_lines(basepath, lines):
    """Overwrite a fileset copy's .adc with these lines."""
    with open(basepath + '.adc', 'w') as f:
        f.write('\n'.join(lines) + '\n')


def edit_adc_line(basepath, line_number, mutate):
    """Replace one 1-based .adc line with ``mutate(fields) -> fields``."""
    lines = read_adc_lines(basepath)
    fields = lines[line_number - 1].split(',')
    lines[line_number - 1] = ','.join(str(f) for f in mutate(fields))
    write_adc_lines(basepath, lines)


def set_adc_column(basepath, line_number, column, value, bin_id=D_BIN_ID):
    """Set one named ADC column ('x', 'width', 'offset', ...) on one line."""
    index = columns_for(bin_id)[column]

    def mutate(fields):
        fields[index] = value
        return fields

    edit_adc_line(basepath, line_number, mutate)


def target_line_numbers(basepath, bin_id=D_BIN_ID):
    """Return the 1-based .adc line numbers that describe an ROI.

    Most ADC lines are triggers with no ROI; mutating one of those changes
    nothing, because the parse path skips it either way.
    """
    cols = columns_for(bin_id)
    numbers = []
    for number, line in enumerate(read_adc_lines(basepath), start=1):
        fields = line.split(',')
        try:
            if int(fields[cols['width']]) and int(fields[cols['height']]):
                numbers.append(number)
        except (IndexError, ValueError):
            continue
    return numbers


def write_synthetic_adc(basepath, n_fields, n_lines=3):
    """Overwrite the .adc with all-integer rows of a given width.

    Used to put a known column count in front of the layout checks without
    inheriting a real file's float columns.
    """
    lines = []
    for i in range(n_lines):
        fields = [str(i + 1)] + [str(j) for j in range(1, n_fields)]
        lines.append(','.join(fields))
    write_adc_lines(basepath, lines)


def read_hdr_lines(basepath):
    """Return the .hdr lines of a fileset copy."""
    with open(basepath + '.hdr', 'r') as f:
        return f.read().splitlines()


def write_hdr_lines(basepath, lines):
    """Overwrite a fileset copy's .hdr with these lines."""
    with open(basepath + '.hdr', 'w') as f:
        f.write('\n'.join(lines) + '\n')


def set_hdr_key(basepath, key, value):
    """Set an RFC 822-style header key, appending it if absent."""
    lines = read_hdr_lines(basepath)
    prefix = f'{key}: '
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = prefix + str(value)
            break
    else:
        lines.append(prefix + str(value))
    write_hdr_lines(basepath, lines)


def remove_file(basepath, ext):
    """Delete one file of a fileset copy."""
    os.remove(f'{basepath}.{ext}')


def truncate_file(basepath, ext, size=0):
    """Truncate one file of a fileset copy to ``size`` bytes."""
    with open(f'{basepath}.{ext}', 'r+b') as f:
        f.truncate(size)
