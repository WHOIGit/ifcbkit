"""
IFCB ROI stitching — composite overlapping I-style ROI pairs and infill gaps.

I-style instruments sometimes produce two consecutive ROIs for a single target.
These overlapping images are composited ("stitched") and the gap between them
infilled with the mean boundary intensity. D-style instruments don't produce
overlapping ROIs, so stitching is a no-op for D-style bins.

PIL-only implementation — no numpy, scipy, or pandas.
"""

from collections.abc import Mapping

from PIL import Image, ImageChops, ImageFilter


# Overlap threshold in pixels — consecutive ROIs must overlap by more than
# this in both X and Y to be considered a stitched pair. Matches pyifcb.
_OVERLAP_THRESHOLD = 2


def detect_pairs(bin_id: str, adc_data: dict) -> list[tuple[int, int]]:
    """Detect stitched ROI pairs from extended ADC data.

    Scans consecutive targets for pairs that share the same trigger number
    and overlap by more than 2px in both dimensions. Only applies to I-style
    bins; returns [] for D-style.

    :param bin_id: the bin ID string
    :param adc_data: dict from parse_adc_bytes(extended=True)
    :returns: list of (target_a, target_b) tuples
    """
    if not bin_id.startswith('I'):
        return []

    targets = sorted(adc_data.keys())
    pairs = []

    for ta, tb in zip(targets, targets[1:]):
        a = adc_data[ta]
        b = adc_data[tb]

        # Must share the same trigger number
        if a.get('trigger') != b.get('trigger'):
            continue

        # Compute bounding box edges
        ax1, ay1 = a['x'], a['y']
        ax2, ay2 = ax1 + a['width'], ay1 + a['height']
        bx1, by1 = b['x'], b['y']
        bx2, by2 = bx1 + b['width'], by1 + b['height']

        # Check overlap exceeds threshold in both dimensions
        if (ax1 < bx2 - _OVERLAP_THRESHOLD and
            ax2 > bx1 + _OVERLAP_THRESHOLD and
            ay1 < by2 - _OVERLAP_THRESHOLD and
            ay2 > by1 + _OVERLAP_THRESHOLD):
            pairs.append((ta, tb))

    return pairs


def stitch_pair(
    adc_a: dict, adc_b: dict,
    image_a: Image.Image, image_b: Image.Image,
) -> tuple[Image.Image, Image.Image]:
    """Composite two overlapping ROIs into a stitched image and gap mask.

    :param adc_a: ADC dict for first ROI (must have x, y, width, height)
    :param adc_b: ADC dict for second ROI
    :param image_a: PIL Image for first ROI
    :param image_b: PIL Image for second ROI
    :returns: (stitched_image, gap_mask) where stitched_image is mode 'L'
              with gap pixels at 0, and gap_mask is mode '1' with white=gap
    """
    # Compute stitched bounding box
    ax1, ay1 = adc_a['x'], adc_a['y']
    ax2, ay2 = ax1 + adc_a['width'], ay1 + adc_a['height']
    bx1, by1 = adc_b['x'], adc_b['y']
    bx2, by2 = bx1 + adc_b['width'], by1 + adc_b['height']

    sx1 = min(ax1, bx1)
    sy1 = min(ay1, by1)
    sx2 = max(ax2, bx2)
    sy2 = max(ay2, by2)
    sw, sh = sx2 - sx1, sy2 - sy1

    # Output image (gap pixels = 0) and mask (all gap initially)
    stitched = Image.new('L', (sw, sh), 0)
    mask = Image.new('1', (sw, sh), 1)
    clear = Image.new('1', (0, 0), 0)  # template for clearing mask regions

    # Paste image_a
    ra_x, ra_y = ax1 - sx1, ay1 - sy1
    stitched.paste(image_a, (ra_x, ra_y))
    clear_a = Image.new('1', (adc_a['width'], adc_a['height']), 0)
    mask.paste(clear_a, (ra_x, ra_y))

    # Paste image_b (overwrites overlap region — matches pyifcb behavior)
    rb_x, rb_y = bx1 - sx1, by1 - sy1
    stitched.paste(image_b, (rb_x, rb_y))
    clear_b = Image.new('1', (adc_b['width'], adc_b['height']), 0)
    mask.paste(clear_b, (rb_x, rb_y))

    return stitched, mask


def infill_stitched_image(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Fill gap region with mean boundary intensity.

    Takes output from stitch_pair(). Finds pixels adjacent to the gap
    (4-connectivity boundary), computes their mean intensity, and fills
    the gap uniformly with that value.

    :param image: stitched image (mode 'L', gap pixels are 0)
    :param mask: gap mask (mode '1', white=gap)
    :returns: infilled image (mode 'L')
    """
    # If no gap pixels, nothing to do
    if not mask.getbbox():
        return image.copy()

    # Dilate mask by 1px using 4-connectivity kernel
    mask_l = mask.convert('L')
    dilate_kernel = ImageFilter.Kernel(
        (3, 3), [0, 1, 0, 1, 1, 1, 0, 1, 0], scale=1, offset=0
    )
    dilated = mask_l.filter(dilate_kernel)
    dilated_binary = dilated.point(lambda p: 1 if p > 0 else 0, '1')

    # Boundary = dilated AND NOT(original mask)
    # These are image-data pixels adjacent to the gap
    mask_inv = ImageChops.invert(mask)
    boundary = ImageChops.logical_and(dilated_binary, mask_inv)

    # Compute mean intensity of boundary pixels
    boundary_pixels = boundary.load()
    image_pixels = image.load()
    w, h = image.size
    total = 0
    count = 0
    for y in range(h):
        for x in range(w):
            if boundary_pixels[x, y]:
                total += image_pixels[x, y]
                count += 1

    fill_value = round(total / count) if count > 0 else 0

    # Fill gap with boundary mean
    result = image.copy()
    result.paste(Image.new('L', image.size, fill_value), mask=mask)

    return result


class BinImages(Mapping):
    """Default image accessor for any bin. Automatically detects and stitches
    overlapping I-style ROI pairs, infills gaps, and excludes second-ROI
    targets from iteration. For D-style bins or bins with no pairs, behaves
    identically to a plain dict of images.

    Implements ``collections.abc.Mapping`` so it is a drop-in replacement
    for the ``dict[int, Image]`` previously returned by image-reading APIs.
    """

    def __init__(self, bin_id: str, adc_data: dict, images: dict, *,
                 stitch: bool = True):
        self._bin_id = bin_id
        self._adc_data = adc_data
        self._raw_images = images
        self._pairs = detect_pairs(bin_id, adc_data) if stitch else []

        # Build stitched results and track excluded targets
        self._stitched = {}      # target_a -> infilled image
        self._raw_stitched = {}  # target_a -> (raw_composite, mask)
        self._excluded = set()   # second targets in pairs

        for ta, tb in self._pairs:
            if ta not in images or tb not in images:
                continue
            composite, mask = stitch_pair(
                adc_data[ta], adc_data[tb],
                images[ta], images[tb],
            )
            self._raw_stitched[ta] = (composite, mask)
            self._stitched[ta] = infill_stitched_image(composite, mask)
            self._excluded.add(tb)

    @property
    def pairs(self) -> list[tuple[int, int]]:
        """Detected (target_a, target_b) pairs."""
        return list(self._pairs)

    # --- Mapping protocol (keys/values/items/get/contains come for free) ---

    def __getitem__(self, target: int) -> Image.Image:
        if target in self._excluded:
            raise KeyError(target)
        if target in self._stitched:
            return self._stitched[target]
        return self._raw_images[target]

    def __iter__(self):
        return iter(t for t in sorted(self._raw_images.keys())
                    if t not in self._excluded)

    def __len__(self):
        return len(self._raw_images) - len(self._excluded)

    # --- Extras beyond Mapping ---

    def get_raw(self, target: int) -> tuple[Image.Image, Image.Image | None]:
        """Get raw composite and gap mask for QC/provenance.

        For stitched targets, returns (raw_composite, gap_mask).
        For non-stitched targets, returns (image, None).
        Raises KeyError for excluded second-ROI targets.
        """
        if target in self._excluded:
            raise KeyError(target)
        if target in self._raw_stitched:
            return self._raw_stitched[target]
        return self._raw_images[target], None


def bin_images(bin_id: str, adc_bytes: bytes, roi_bytes: bytes, *,
               stitch: bool = True) -> BinImages:
    """One-stop factory: parse ADC, extract ROIs, return stitched BinImages.

    This is the single integration point for stitching. All higher-level
    image-reading APIs delegate here.

    :param bin_id: the bin ID string
    :param adc_bytes: raw bytes of the .adc file
    :param roi_bytes: raw bytes of the .roi file
    :param stitch: if True (default), auto-stitch I-style overlapping pairs
    :returns: BinImages mapping of {target_number: PIL.Image}
    """
    from .adc import parse_adc_bytes
    from .roi import extract_roi_images

    adc = parse_adc_bytes(bin_id, adc_bytes, extended=True)
    images = extract_roi_images(bin_id, adc_bytes, roi_bytes)
    return BinImages(bin_id, adc, images, stitch=stitch)
