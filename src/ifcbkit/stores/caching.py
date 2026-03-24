"""
Caching stores for IFCB data.

CachingBinStore: two-tier (S3 cache over filesystem source of truth)
CachingRoiStore: three-tier (memory -> S3 -> filesystem)
"""

from . import AsyncBinStore, AsyncRoiStore
from .s3 import AsyncS3BinStore, AsyncS3RoiStore, AsyncDictRoiStore
from .filesystem import AsyncFilesystemBinStore, AsyncFilesystemRoiStore


class CachingBinStore(AsyncBinStore):
    """Two-tier bin store: S3 as cache, filesystem as source of truth.

    On get: tries S3 first; on miss falls back to filesystem and promotes
    the file to S3 so subsequent reads are served from S3.
    """

    def __init__(
        self,
        fs: AsyncBinStore | None = None,
        s3: AsyncS3BinStore | None = None,
    ):
        if not fs and not s3:
            raise ValueError("CachingBinStore requires at least one of fs or s3")
        self.fs = fs
        self.s3 = s3

    async def exists(self, key: str) -> bool:
        if self.s3 and await self.s3.exists(key):
            return True
        if self.fs and await self.fs.exists(key):
            return True
        return False

    async def get(self, key: str) -> bytes:
        # Try S3 first (already promoted)
        if self.s3 and await self.s3.exists(key):
            return await self.s3.get(key)
        # Fall back to filesystem; promote to S3
        if self.fs:
            data = await self.fs.get(key)
            if self.s3:
                try:
                    await self.s3.put(key, data)
                except Exception:
                    pass  # best-effort
            return data
        raise KeyError(key)

    async def read_images(self, bin_id: str, rois=None) -> dict:
        """Delegate to the most efficient available store.

        Prefers the filesystem store (seek-based, no full .roi load into memory).
        Falls back to S3 if the bin is absent from the filesystem.
        """
        if self.fs:
            try:
                return await self.fs.read_images(bin_id, rois=rois)
            except KeyError:
                pass
        if self.s3:
            return await self.s3.read_images(bin_id, rois=rois)
        raise KeyError(bin_id)

    async def get_path(self, key: str) -> str | None:
        if self.fs:
            return await self.fs.get_path(key)
        return None

    async def iter_images(self, bin_id: str, rois=None):
        if self.fs:
            try:
                async for item in self.fs.iter_images(bin_id, rois=rois):
                    yield item
                return
            except KeyError:
                pass
        if self.s3:
            async for item in self.s3.iter_images(bin_id, rois=rois):
                yield item
            return
        raise KeyError(bin_id)

    async def put(self, key: str, data: bytes) -> None:
        if self.s3:
            await self.s3.put(key, data)
            return
        raise NotImplementedError("CachingBinStore requires an S3 store to support put")


class CachingRoiStore(AsyncRoiStore):
    """Three-tier ROI store: memory cache -> S3 -> filesystem.

    Read from cache first; if miss, read from S3; if miss, read from filesystem.
    Write to both cache and S3.
    """

    def __init__(
        self,
        cache: AsyncRoiStore | None = None,
        s3: AsyncS3RoiStore | None = None,
        fs: AsyncFilesystemRoiStore | None = None,
    ):
        self.cache_store = cache if cache is not None else AsyncDictRoiStore()
        self.s3_store = s3
        self.fs_store = fs

    async def get(self, roi_id: str) -> bytes:
        # try cache
        if await self.cache_store.exists(roi_id):
            return await self.cache_store.get(roi_id)
        # try S3
        if self.s3_store and await self.s3_store.exists(roi_id):
            data = await self.s3_store.get(roi_id)
            await self.cache_store.put(roi_id, data)
            return data
        # try filesystem
        if self.fs_store and await self.fs_store.exists(roi_id):
            data = await self.fs_store.get(roi_id)
            if self.s3_store:
                try:
                    await self.s3_store.put(roi_id, data)
                except Exception:
                    pass
            await self.cache_store.put(roi_id, data)
            return data
        raise KeyError(f"ROI ID {roi_id} not found in any store")

    async def put(self, roi_id: str, image_data: bytes):
        if self.s3_store:
            await self.s3_store.put(roi_id, image_data)
            return
        raise RuntimeError("CachingRoiStore requires an S3 store to support put")

    async def exists(self, roi_id: str) -> bool:
        if await self.cache_store.exists(roi_id):
            return True
        if self.s3_store and await self.s3_store.exists(roi_id):
            return True
        if self.fs_store and await self.fs_store.exists(roi_id):
            return True
        return False
