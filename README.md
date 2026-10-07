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

## Quality control

`ifcbkit.qc` reports whether data is **intact** — present, parseable, internally consistent. It does not judge whether data is *good*: no `ml_analyzed`, no bead/blank detection, no trigger-rate or class-score plausibility. Those are analysis, not integrity.

```python
from ifcbkit.qc import check_bin, check_collection, Cost

report = check_bin('/data/D20130526/D20130526T095207_IFCB013')
report.ok            # False if anything of 'error' severity was found
report.errors        # [Finding(code='missing_roi', ...), ...]
report.skipped       # {code: why} — checks that could not be evaluated
report.to_jsonl()    # a 'report' record, then one 'finding' record each

# The shape of a whole tree: incomplete filesets, duplicate PIDs, day-dir
# mismatches, filesets a listing filter would silently drop.
tree = check_collection('/data', adcmod_root='/adcmod')
```

Each finding carries a `code`, a `severity` fixed by the check registry, the `subject` it is about, a rendered `message`, and structured `detail`. Severities are `error` (unusable), `warning` (usable but something is off), and `info` (notable, not a defect). **The library states facts; the consumer sets policy** — an empty bin is reported `zero_rois` at `info` severity precisely because ifcbdb treats that as bad data and ifcb-ingest treats it as valid.

A few checks are **opt-in**: they state something true of nearly every bin, or encode one site's layout convention as a rule, so leaving them on would bury the findings that matter. `adc_zero_geometry` is the clearest case — most triggers in a real bin record no ROI, so it fires on essentially every bin ever collected. Ask for them by code, or `'all'`:

```python
report = check_bin(basepath, enable=('adc_zero_geometry',))
```

An opt-in check that was not requested lands in `report.skipped`, so a report never implies it passed. `ifcbkit-qc --list-checks` marks them `[opt-in]`.

Checks are grouped by how much I/O they need, so a scan can be as cheap as it needs to be:

| `Cost` | Reads | Answers |
|--------|-------|---------|
| `stat` | names and `os.stat` | presence, sizes, identifiers, collection shape |
| `parse` (default) | .hdr and .adc; stats the .roi | header and ADC integrity, **and every ADC↔ROI byte-range check** |
| `full` | decodes ROI images, opens product containers | image decode failures, features/class/blob integrity |

The ADC↔ROI consistency checks (`roi_offset_past_eof`, `roi_short_read`, `roi_overlapping_targets`, `roi_unaccounted_bytes`) need only the ADC offsets and the .roi file size, so they run at `parse`.

ADC and header findings come from the optional `diagnostics` channel on `iter_adc_targets` and `parse_hdr` rather than from a second parser, so QC cannot disagree with the parse path consumers actually use:

```python
diagnostics = []
targets = list(iter_adc_targets(bin_id, adc_bytes, diagnostics=diagnostics))
# diagnostics: [{'line': 42, 'reason': 'zero_geometry', 'text': '...', 'n_fields': 24}, ...]
```

Every ADC line is accounted for exactly once — either as a yielded target or as one diagnostic. Passing no channel (the default) leaves behavior and output byte-identical.

### Where products live

Products are rarely stored next to the raw data, so nothing here assumes that. The default for a bin is its own directory; a real archive gives each product type a root of its own:

```python
report = check_bin(
    '/data/raw/D20130526/D20130526T095207_IFCB013',
    cost=Cost.FULL, expect=('features', 'class'),
    product_dirs={
        'features': '/data/features',   # /data/features/D20130526/..._fea_v2.csv
        'class': '/data/class',         # /data/class/2013/D20130526/..._class.h5
        'blobs': '/data/blobs',
    })
```

Each root is searched by convention first — the root itself, then `<day_dir>/`, `<year>/<day_dir>/`, `<year>/` — and only falls back to a recursive walk if none of those hold the file. That fallback walks the whole product root, once per bin, so `ifcbkit-qc` defaults to `--product-search auto`: on for a single bin, off when walking a tree, where it would repeat for every bin. `--product-search always` forces it on, `never` off; the library-level switch is `product_search=False`. Skipping it costs you files in unconventional layouts. A product type with no root given is not searched at all, and `product_missing` names the directory it looked in. When several versions of a product are present, the highest version wins.

### `ifcbkit-qc`

```bash
ifcbkit-qc /data/D20130526/D20130526T095207_IFCB013   # one bin
ifcbkit-qc --cost stat /data                          # a whole tree
ifcbkit-qc --json /data | jq -c 'select(.severity=="error")'

ifcbkit-qc -q /data               # only subjects with something to report
ifcbkit-qc --list-checks          # every check, with severity and cost
ifcbkit-qc --expect features,blobs /data/bin  # product_missing fires only for these
ifcbkit-qc --ignore zero_rois --strict /data  # warnings also fail
ifcbkit-qc --enable adc_zero_geometry /data   # opt-in checks, by code or "all"

# products in their own trees (repeat --product-dir per type)
ifcbkit-qc --cost full --expect features,class /data/raw \
  --product-dir features=/data/features --product-dir class=/data/class
ifcbkit-qc --products-root /data/products /data/raw   # one root for all types
```

### Data still arriving

ROI telemetry can lag the `.hdr` and `.adc` by hours, so a live directory routinely holds bins whose image data has not landed yet. `--roi-optional` (`roi_optional=True`) says so: an absent `.roi` stops being an error, and a fileset whose *only* absent file is the `.roi` is no longer reported incomplete. A fileset missing its `.hdr` or `.adc` still is — a distinction `--ignore fileset_incomplete` cannot make, since that would silence genuinely truncated filesets too.

```bash
ifcbkit-qc --roi-optional /data/today
```

The absence is still accounted for, as a skip rather than a finding, because the ADC↔ROI byte-range checks could not run and the report must not imply they passed:

```
D20220124T201049_IFCB127: no findings
  skipped  missing_roi    the .roi file has not arrived (roi_optional); the ADC-to-ROI checks could not run
```

That also means such bins stay visible under `-q`. To drop them entirely once you have accepted them, add `--ignore missing_roi`.

Scanning an archive, `-q` / `--quiet` drops the subjects with nothing to say, leaving the problems and a count of what was checked:

```
$ ifcbkit-qc -q /data
/data: 1 error
  error    fileset_incomplete    D20130526T125207_IFCB013 has .adc, .hdr but is missing .roi.
D20130526T125207_IFCB013: 1 error
  error    missing_roi           The .roi file is absent.
5 subject(s) checked, 2 with errors (3 with nothing to report, not shown)
not run for any subject: adc_zero_geometry, mixed_instruments (not requested (opt-in check))
```

A subject whose check was *skipped* or *truncated* is still shown under `-q`: not knowing something is not the same as finding nothing wrong. The summary line always says how many subjects were checked, so hiding the clean ones never hides that they were examined.

`--json` emits three kinds of record, each tagged with `type`:

```
{"type":"run","cost":"parse","n_subjects":3,"skipped":{"adc_zero_geometry":"not requested (opt-in check)"}}
{"type":"report","subject":"D20220124T201049_IFCB127","cost":"parse","n_findings":0,"n_errors":0}
{"type":"report","subject":"D20220124T203435_IFCB127","cost":"parse","n_findings":1,"n_errors":1}
{"type":"finding","code":"missing_roi","severity":"error","subject":"D20220124T203435_IFCB127",...}
```

Every subject gets a `report` record, including one with nothing wrong, so a clean bin leaves proof it was examined rather than looking indistinguishable from a bin nobody opened. A subject's record carries `skipped` (checks that could not be evaluated on *it*) and `truncated` (findings counted but not listed), both omitted when empty — a findings-only stream would report a skipped check and a passed check identically, which for an integrity tool means silence reads as health.

Anything constant across the invocation goes in the single leading `run` record instead of on every subject: on a real archive, repeating it per bin is thousands of identical lines, which is its own way of hiding a finding. Which opt-in checks went unrequested is the usual case.

```bash
# findings only — a filter on a finding field passes over the other records
ifcbkit-qc --json /data | jq -c 'select(.severity=="error")'

# bins where a check could not be evaluated (h5py absent, say)
ifcbkit-qc --json /data | jq -c 'select(.type=="report" and (.skipped|length>0))'

# confirm the sweep covered what you expected
ifcbkit-qc --json /data | jq -c 'select(.type=="run")'
```

Exit status is `0` for no errors, `1` when something of `error` severity was found (with `--strict`, also `warning`), and `2` if QC itself could not run.

## Dependencies

**Required:** Python 3.10+, Pillow, aiofiles

**Optional:** `amplify-storage-utils` (for S3/caching stores — install with `pip install -e ".[s3]"`); `h5py` (for class-score reading and the class-score QC checks — `pip install -e ".[hdf5]"`; without it those checks are reported in `Report.skipped` rather than failing)

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

### The single ADC parse path

`iter_adc_targets` is the one place ifcbkit parses ADC lines. It yields a full record per usable ROI — `target`, `roi_id`, `trigger`, `x`, `y`, `width`, `height`, `offset` — and everything else that reads ADC data is a projection or filter of it. A target is usable only if all of those columns parse and the ROI has non-zero area, so ADC parsing and ROI extraction always agree on which targets exist.

Use it directly to avoid parsing the ADC twice when you need both metadata and images:

```python
from ifcbkit import iter_adc_targets, extract_roi_images_from_targets

targets = list(iter_adc_targets(bin_id, adc_bytes))
images = extract_roi_images_from_targets(targets, roi_bytes)
```

## Note: corrected ADC files (`adcmod`)

Some datasets (e.g. MVCO) keep corrected ADC files outside the raw data directory so the raw data stays untouched. These live in an `adcmod` directory that is strictly a sibling of the raw data root, laid out as `adcmod/<day>/<pid>.adc.mod`, where `<day>` is the name of the directory containing the raw fileset. The `.adc.mod` format is byte-compatible with `.adc`.

`ifcbkit` resolves these transparently: when listing or fetching a fileset it uses the corrected ADC in place of the raw `.adc` if one exists. Only the ADC file is substituted — `.hdr` and `.roi` always come from the raw data directory — and a raw `.adc` must still be present for the bin to be discovered. `adcmod_path(fileset_dir, pid, root_path)` returns the path a correction would have.

QC reports on corrections rather than silently preferring them: `adcmod_row_delta` and `adcmod_geometry_delta` are `info` (changing targets and geometry is what a correction is *for*), while `adcmod_invalid` is an error and `adcmod_orphan` — a correction with no raw fileset — is a warning. Product coverage, though, is compared against the *corrected* target set when a usable correction exists, because that is the ADC consumers read and the one the products were derived from — checking products against the raw ADC would invent coverage findings on every corrected bin.

```python
report = check_bin('/data/D20130526/D20130526T095207_IFCB013', root_path='/data')
```

## Note: parse failures are reported, not raised

`parse_hdr` no longer raises when a header value fails its schema cast, and no longer raises `IndexError` on a header truncated after its banner line. The raw value is kept, the failure is recorded on the `diagnostics` channel, and QC reports it as `hdr_cast_failure` or `hdr_truncated`. One bad field does not cost you the rest of the header. Well-formed headers parse exactly as before.
