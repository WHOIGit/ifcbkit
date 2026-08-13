"""
IFCB ROI (.roi) binary file reading.

ROI files are binary: one byte per pixel (8-bit grayscale), no header.
Seek to offset from ADC, read width * height bytes, construct PIL Image
via Image.frombuffer() — zero-copy.

ADC column layout is not known here: this module consumes target records
produced by :func:`ifcbkit.adc.iter_adc_targets`.
"""

from io import BytesIO

from PIL import Image

from .adc import iter_adc_targets


def extract_roi_images_from_targets(targets, roi_bytes: bytes, rois=None) -> dict:
    """Extract PIL Images from already-parsed ADC target records.

    Use this when the ADC has already been parsed, to avoid parsing it twice.

    :param targets: iterable of records from
      :func:`ifcbkit.adc.iter_adc_targets`
    :param roi_bytes: raw bytes of the .roi file
    :param rois: optional set of target numbers to extract (None = all)
    :returns: dict of {target_number: PIL.Image}
    """
    images = {}
    roi_buffer = BytesIO(roi_bytes)
    for record in targets:
        target = record['target']
        if rois is not None and target not in rois:
            continue
        width, height = record['width'], record['height']
        roi_buffer.seek(record['offset'])
        data = roi_buffer.read(width * height)
        images[target] = Image.frombuffer(
            'L', (width, height), data, 'raw', 'L', 0, 1)
    return images


def extract_roi_images(bin_id: str, adc_bytes: bytes, roi_bytes: bytes, rois=None) -> dict:
    """Extract PIL Images from .adc and .roi bytes.

    :param bin_id: the bin ID string (needed to determine column layout)
    :param adc_bytes: raw bytes of the .adc file
    :param roi_bytes: raw bytes of the .roi file
    :param rois: optional set of target numbers to extract (None = all)
    :returns: dict of {target_number: PIL.Image}
    """
    return extract_roi_images_from_targets(
        iter_adc_targets(bin_id, adc_bytes), roi_bytes, rois=rois)


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
