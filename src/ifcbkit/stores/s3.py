"""
S3-backed stores for IFCB bin data and ROI images.

Requires amplify-storage-utils as an optional dependency. Import this
module only if amplify-storage-utils is installed.
"""

import asyncio

try:
    from storage.s3 import BucketStore
    from storage.utils import KeyTransformingStore, PrefixKeyTransformer
    from storage.object import DictStore
    _HAS_STORAGE = True
except ImportError:
    _HAS_STORAGE = False

from ..identifiers import parse_roi_id
from . import AsyncBinStore, SyncRoiStore, AsyncRoiStore


def _require_storage():
    if not _HAS_STORAGE:
        raise ImportError(
            "S3 stores require amplify-storage-utils. "
            "Install it with: pip install amplify-storage-utils"
        )


class IfcbPidTransformer:
    """Transforms IFCB PIDs to/from S3 keys.

    Transforms PIDs like 'D20250114T172241_IFCB109_00002' to S3 keys like
    '2025/D20250114T172241_IFCB109/00002.png'.
    """

    def transform_key(self, pid: str) -> str:
        bin_lid, roi_number = parse_roi_id(pid)
        if bin_lid.startswith("D") and len(bin_lid) >= 5:
            year = bin_lid[1:5]
        else:
            year = "legacy"
        return f"{year}/{bin_lid}/{roi_number:05d}.png"

    def reverse_transform_key(self, s3_key: str) -> str:
        parts = s3_key.split('/')
        if len(parts) < 3:
            raise ValueError(f"Invalid S3 key format: {s3_key}")
        bin_lid = parts[-2]
        filename = parts[-1]
        if not filename.endswith('.png'):
            raise ValueError(f"Expected .png file, got: {filename}")
        roi_number = filename[:-4]
        return f"{bin_lid}_{roi_number}"


class IfcbBinKeyTransformer:
    """Transforms IFCB bin file basenames to/from S3 keys.

    Transforms keys like 'D20250114T172241_IFCB109.hdr' to S3 keys like
    '2025/D20250114T172241_IFCB109.hdr'.
    """

    def transform_key(self, key: str) -> str:
        bin_id, ext = key.rsplit('.', 1)
        if bin_id.startswith("D") and len(bin_id) >= 5:
            year = bin_id[1:5]
        else:
            year = "legacy"
        return f"{year}/{bin_id}.{ext}"

    def reverse_transform_key(self, s3_key: str) -> str:
        return s3_key.split('/')[-1]


def list_roi_ids_from_s3(bucket_store, bin_id: str, prefix: str = "") -> list:
    """List ROI IDs for a given bin from S3.

    :param bucket_store: BucketStore instance for S3 access
    :param bin_id: IFCB bin ID
    :param prefix: optional S3 key prefix
    :returns: sorted list of ROI IDs
    """
    _require_storage()
    if bin_id.startswith("D") and len(bin_id) >= 5:
        year = bin_id[1:5]
    else:
        year = "legacy"

    prefix = prefix.rstrip("/") if prefix else ""
    if prefix:
        search_prefix = f"{prefix}/{year}/{bin_id}/"
    else:
        search_prefix = f"{year}/{bin_id}/"

    roi_ids = []
    for key in bucket_store.keys(prefix=search_prefix):
        filename = key.split("/")[-1]
        if not filename.endswith(".png"):
            continue
        try:
            target_str = filename[:-4]
            target = int(target_str)
            roi_ids.append(f"{bin_id}_{target:05d}")
        except ValueError:
            continue

    roi_ids.sort()
    return roi_ids


class AsyncS3BinStore(AsyncBinStore):
    """S3-backed async bin store.

    Uses KeyTransformingStore with IfcbBinKeyTransformer to map bin file
    basenames to S3 keys of the form '{year}/{bin_id}.{ext}'.
    """

    def __init__(self, s3_bucket: str, s3_client=None, s3_prefix: str | None = None):
        _require_storage()
        bucket_store = BucketStore(s3_bucket, s3_client)
        if s3_prefix:
            prefix_transformer = PrefixKeyTransformer(prefix=s3_prefix.rstrip("/") + "/")
            inner_store = KeyTransformingStore(bucket_store, prefix_transformer)
        else:
            inner_store = bucket_store
        self._store = KeyTransformingStore(inner_store, IfcbBinKeyTransformer())

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._store.exists, key)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._store.get, key)

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._store.put, key, data)


class S3RoiStore(SyncRoiStore):
    """An S3-based synchronous ROI store."""

    def __init__(self, s3_bucket: str, s3_client=None, s3_prefix: str | None = None):
        _require_storage()
        bucket_store = BucketStore(s3_bucket, s3_client)
        if s3_prefix:
            prefix_transformer = PrefixKeyTransformer(prefix=s3_prefix.rstrip("/") + "/")
            prefix_store = KeyTransformingStore(bucket_store, prefix_transformer)
        else:
            prefix_store = bucket_store
        self.store = KeyTransformingStore(prefix_store, IfcbPidTransformer())

    def exists(self, roi_id: str) -> bool:
        return self.store.exists(roi_id)

    def get(self, roi_id: str) -> bytes:
        return self.store.get(roi_id)

    def put(self, roi_id: str, image_data: bytes):
        return self.store.put(roi_id, image_data)


class AsyncS3RoiStore(AsyncRoiStore):
    """An S3-based asynchronous ROI store."""

    def __init__(self, s3_bucket: str, s3_client=None, s3_prefix: str | None = None):
        self.store = S3RoiStore(s3_bucket, s3_client, s3_prefix)

    async def exists(self, roi_id: str) -> bool:
        return await asyncio.to_thread(self.store.exists, roi_id)

    async def get(self, roi_id: str) -> bytes:
        return await asyncio.to_thread(self.store.get, roi_id)

    async def put(self, roi_id: str, image_data: bytes):
        return await asyncio.to_thread(self.store.put, roi_id, image_data)


class AsyncDictRoiStore(AsyncRoiStore):
    """An in-memory async ROI store using a dictionary."""

    def __init__(self):
        _require_storage()
        self.store = DictStore()

    async def exists(self, roi_id: str) -> bool:
        return self.store.exists(roi_id)

    async def get(self, roi_id: str) -> bytes:
        return self.store.get(roi_id)

    async def put(self, roi_id: str, image_data: bytes):
        self.store.put(roi_id, image_data)
