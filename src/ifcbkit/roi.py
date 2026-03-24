"""
IFCB ROI (.roi) binary file reading.

ROI files are binary: one byte per pixel (8-bit grayscale), no header.
Seek to offset from ADC, read width * height bytes, construct PIL Image
via Image.frombuffer() — zero-copy.
"""

from io import BytesIO

from PIL import Image

from .identifiers import add_target


def extract_roi_images(bin_id: str, adc_bytes: bytes, roi_bytes: bytes, rois=None) -> dict:
    """Extract PIL Images from .adc and .roi bytes.

    :param bin_id: the bin ID string (needed to determine column layout)
    :param adc_bytes: raw bytes of the .adc file
    :param roi_bytes: raw bytes of the .roi file
    :param rois: optional set of target numbers to extract (None = all)
    :returns: dict of {target_number: PIL.Image}
    """
    if bin_id.startswith('I'):
        w_col, h_col, offset_col = 11, 12, 13
    else:
        w_col, h_col, offset_col = 15, 16, 17

    images = {}
    roi_buffer = BytesIO(roi_bytes)
    for i, line in enumerate(adc_bytes.decode('utf-8', errors='replace').splitlines()):
        if rois is not None and (i + 1) not in rois:
            continue
        fields = line.strip().split(',')
        try:
            width = int(fields[w_col])
            height = int(fields[h_col])
            offset = int(fields[offset_col])
        except (ValueError, IndexError):
            continue
        if width == 0 or height == 0:
            continue
        roi_buffer.seek(offset)
        data = roi_buffer.read(width * height)
        images[i + 1] = Image.frombuffer('L', (width, height), data, 'raw', 'L', 0, 1)
    return images


def extract_roi_image(roi_file, width: int, height: int, offset: int) -> Image.Image:
    """Extract a single ROI image from an open file-like object.

    :param roi_file: file-like object (opened in binary mode)
    :param width: image width in pixels
    :param height: image height in pixels
    :param offset: byte offset into the .roi file
    :returns: PIL Image (8-bit grayscale)
    """
    roi_file.seek(offset)
    data = roi_file.read(width * height)
    return Image.frombuffer('L', (width, height), data, 'raw', 'L', 0, 1)
