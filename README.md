# ifcbkit

A lean, modern Python library for parsing and accessing IFCB (Imaging FlowCytobot) raw data and products. PIL-only — no numpy, scipy, or pandas.

## Install

```bash
pip install -e .

# With S3 store support:
pip install -e ".[s3]"
```

## Filesystem data access

### Finding data

IFCB raw data lives in directory trees containing `.hdr` / `.adc` / `.roi` file triplets. Use `SyncIfcbDataDirectory` (or its async counterpart) to discover and access them:

```python
from ifcbkit import SyncIfcbDataDirectory

dd = SyncIfcbDataDirectory('/path/to/ifcb/data')

# List all filesets
for fileset in dd.list():
    print(fileset['pid'])  # e.g. 'D20221227T093138_IFCB127'

# Filter the listing by timestamp range and/or instrument.
# The range is half-open [start_time, end_time); naive datetimes are UTC.
from datetime import datetime, timezone

for fileset in dd.list(
    start_time=datetime(2022, 12, 1, tzinfo=timezone.utc),
    end_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
    instrument=127,           # int, or an iterable like [127, 130]
):
    print(fileset['pid'])

# Check if a specific bin exists
dd.exists('D20221227T093138_IFCB127')

# Get file paths for a bin
paths = dd.paths('D20221227T093138_IFCB127')
# {'hdr': '.../.hdr', 'adc': '.../.adc', 'roi': '.../.roi'}
```

### Parsing metadata

```python
from ifcbkit import parse_hdr_file, parse_adc_file

# Header metadata (instrument settings, context)
hdr = parse_hdr_file('/path/to/bin.hdr')

# ADC metadata (per-ROI coordinates, dimensions)
adc = parse_adc_file('D20221227T093138_IFCB127', '/path/to/bin.adc')
# {1: {'roi_id': '...', 'x': 10, 'y': 20, 'width': 50, 'height': 30}, ...}
```

### Reading images

```python
dd = SyncIfcbDataDirectory('/path/to/ifcb/data')

# Read all images from a bin
images = dd.read_images('D20221227T093138_IFCB127')
for target in images:
    img = images[target]  # PIL Image
    img.save(f'{target}.png')

# Read a single image by ROI ID
img = dd.read_image('D20221227T093138_IFCB127_00003')
```

**From raw bytes:**

```python
from ifcbkit import bin_images

with open('D20221227T093138_IFCB127.adc', 'rb') as f:
    adc_bytes = f.read()
with open('D20221227T093138_IFCB127.roi', 'rb') as f:
    roi_bytes = f.read()

images = bin_images('D20221227T093138_IFCB127', adc_bytes, roi_bytes)
# Returns BinImages (a Mapping[int, Image]) — drop-in for dict
```

**Via stores:**

```python
from ifcbkit import AsyncFilesystemBinStore

store = AsyncFilesystemBinStore('/path/to/ifcb/data')
images = await store.read_images('D20221227T093138_IFCB127')
```

## Identifier parsing

```python
from ifcbkit import parse_bin_id, parse_roi_id, bin_timestamp, add_target

# Parse bin IDs
info = parse_bin_id('D20221227T093138_IFCB127')

# Extract timestamp
ts = bin_timestamp('D20221227T093138_IFCB127')  # datetime object

# Build ROI IDs
roi_id = add_target('D20221227T093138_IFCB127', 5)
# 'D20221227T093138_IFCB127_00005'

# Parse ROI IDs back
bin_id, target_num = parse_roi_id('D20221227T093138_IFCB127_00005')
```

## Product file discovery

```python
from ifcbkit import sync_blob_path, sync_features_path, sync_class_scores_path

blob_file = sync_blob_path('/data/products', 'D20221227T093138_IFCB127')
features_file = sync_features_path('/data/products', 'D20221227T093138_IFCB127')
```

## Dependencies

**Required:** Python 3.10+, Pillow, aiofiles

**Optional:** `amplify-storage-utils` (for S3/caching stores — install with `pip install -e ".[s3]"`)

---

## Note: I-style bin stitching

Older I-style IFCB instruments (IFCB1, IFCB5, etc.) sometimes produced two consecutive ROIs for a single target — overlapping images with a gap between them. All image-reading APIs handle this transparently: overlapping pairs are automatically composited and gap-infilled. D-style bins (the vast majority of data) are unaffected.

For QC or provenance work, `BinImages` exposes stitching details:

```python
images = dd.read_images('IFCB1_2014_001_120000')

images.pairs           # [(3, 4), (17, 18), ...] — detected stitched pairs
images.get_raw(3)      # (raw_composite, gap_mask) before infill
```

To disable stitching:

```python
from ifcbkit import bin_images

images = bin_images(bin_id, adc_bytes, roi_bytes, stitch=False)
```

Extended ADC mode provides the trigger numbers used for pair detection:

```python
adc = parse_adc_file(bin_id, '/path/to/bin.adc', extended=True)
# adds 'trigger' and 'offset' to each target dict
```

Low-level stitching functions (`detect_pairs`, `stitch_pair`, `infill_stitched_image`) and raw extraction utilities (`extract_roi_images`, `extract_roi_image`) are available for specialized use cases.

## Note: corrected ADC files (`adcmod`)

Some datasets (e.g. MVCO) keep corrected ADC files outside the raw data directory so the raw data stays untouched. These live in an `adcmod` directory that is strictly a sibling of the raw data root, laid out as `adcmod/<day>/<pid>.adc.mod`, where `<day>` is the name of the directory containing the raw fileset. The `.adc.mod` format is byte-compatible with `.adc`.

`ifcbkit` resolves these transparently: when listing or fetching a fileset it uses the corrected ADC in place of the raw `.adc` if one exists. Only the ADC file is substituted — `.hdr` and `.roi` always come from the raw data directory — and a raw `.adc` must still be present for the bin to be discovered.
