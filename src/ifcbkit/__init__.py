"""
ifcbkit — A lean, modern Python library for parsing and accessing
IFCB (Imaging FlowCytobot) raw data and products.

Public API surface: everything you'd import from ifcbkit directly.
"""

# Identifiers
from .identifiers import (
    parse_bin_id,
    parse_roi_id,
    parse_pid,
    add_target,
    bin_timestamp,
    bin_day_dir,
    bin_year,
    bin_instrument_id,
    parse_i_style_bin_id,
    parse_d_style_bin_id,
    parse_target,  # backward-compat alias for parse_roi_id
)

# Header parsing
from .header import (
    parse_hdr,
    parse_hdr_file,
    parse_hdr_bytes,
)

# ADC parsing
from .adc import (
    iter_adc_targets,
    targets_to_dict,
    parse_adc_bytes,
    parse_adc_file,
    parse_adc_line,
)

# ROI reading
from .roi import (
    extract_roi_images,
    extract_roi_images_from_targets,
    extract_roi_image,
)

# Fileset discovery
from .fileset import (
    validate_path,
    make_fileset_filter,
    async_list_filesets,
    sync_list_filesets,
    async_list_data_dirs,
    sync_list_data_dirs,
    async_find_fileset,
    sync_find_fileset,
    SyncIfcbDataDirectory,
    AsyncIfcbDataDirectory,
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
)

# Products
from .products import (
    async_find_product_file,
    async_list_product_files,
    async_blob_path,
    async_class_scores_path,
    async_features_path,
    read_blobs,
    read_class_scores,
    read_features,
    sync_find_product_file,
    sync_list_product_files,
    sync_blob_path,
    sync_class_scores_path,
    sync_features_path,
    ClassScoresRows,
)

# Store base classes (always available)
from .stores import (
    AsyncBinStore,
    SyncRoiStore,
    AsyncRoiStore,
)

# Filesystem stores (always available)
from .stores.filesystem import (
    AsyncFilesystemBinStore,
    SyncFilesystemRoiStore,
    AsyncFilesystemRoiStore,
)

# Stitching
from .stitching import (
    detect_pairs,
    stitch_pair,
    infill_stitched_image,
    BinImages,
    bin_images,
)

# S3 and caching stores are NOT imported here — they require
# amplify-storage-utils. Import them explicitly:
#
#   from ifcbkit.stores.s3 import AsyncS3BinStore, S3RoiStore, ...
#   from ifcbkit.stores.caching import CachingBinStore, CachingRoiStore


__version__ = '0.3.1'
