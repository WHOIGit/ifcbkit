"""
Filesystem-backed stores for IFCB bin data and ROI images.
"""

import os
from io import BytesIO

import aiofiles

from ..identifiers import parse_roi_id
from ..fileset import (
    async_find_fileset, async_resolve_adc_path,
    SyncIfcbDataDirectory, AsyncIfcbDataDirectory,
    DEFAULT_INCLUDE, DEFAULT_EXCLUDE,
)
from . import AsyncBinStore, SyncRoiStore, AsyncRoiStore


class AsyncFilesystemBinStore(AsyncBinStore):
    """Filesystem-backed async bin store.

    Searches for filesets under root_path using include/exclude logic.
    """

    def __init__(
        self,
        root_path: str,
        include=DEFAULT_INCLUDE,
        exclude=DEFAULT_EXCLUDE,
    ):
        self.root_path = root_path
        self.include = include
        self.exclude = exclude

    async def _find_path(self, bin_id: str, ext: str) -> str | None:
        """Return absolute path to the given bin file, or None if not found."""
        basepath = await async_find_fileset(
            self.root_path, bin_id,
            include=self.include, exclude=self.exclude,
            require_adc=(ext in ('adc', 'roi')),
            require_roi=(ext == 'roi'),
        )
        if basepath is None:
            return None
        if ext == 'adc':
            return await async_resolve_adc_path(
                os.path.dirname(basepath), os.path.basename(basepath),
                self.root_path,
            )
        return f"{basepath}.{ext}"

    async def exists(self, key: str) -> bool:
        bin_id, ext = key.rsplit('.', 1)
        return await self._find_path(bin_id, ext) is not None

    async def get(self, key: str) -> bytes:
        bin_id, ext = key.rsplit('.', 1)
        path = await self._find_path(bin_id, ext)
        if path is None:
            raise KeyError(key)
        async with aiofiles.open(path, 'rb') as f:
            return await f.read()

    async def get_path(self, key: str) -> str | None:
        bin_id, ext = key.rsplit('.', 1)
        return await self._find_path(bin_id, ext)


class SyncFilesystemRoiStore(SyncRoiStore):
    """A filesystem-based synchronous ROI store."""

    def __init__(self, base_path: str, file_type: str = "png"):
        self.dd = SyncIfcbDataDirectory(base_path, require_roi=True)
        file_type = file_type.lower().lstrip(".")
        if file_type == "jpeg":
            file_type = "jpg"
        if file_type not in {"png", "jpg"}:
            raise ValueError(f"Unsupported file_type: {file_type!r} (expected 'png' or 'jpg')")
        self.file_type = file_type

    def exists(self, roi_id: str) -> bool:
        bin_id, _ = parse_roi_id(roi_id)
        return self.dd.exists(bin_id)

    def get(self, roi_id: str) -> bytes:
        image = self.dd.read_image(roi_id)
        image_data = BytesIO()
        fmt = "JPEG" if self.file_type == "jpg" else "PNG"
        image.save(image_data, format=fmt)
        return image_data.getvalue()


class AsyncFilesystemRoiStore(AsyncRoiStore):
    """A filesystem-based async ROI store."""

    def __init__(self, base_path: str, file_type: str = "png"):
        self.dd = AsyncIfcbDataDirectory(base_path, require_roi=True)
        file_type = file_type.lower().lstrip(".")
        if file_type == "jpeg":
            file_type = "jpg"
        if file_type not in {"png", "jpg"}:
            raise ValueError(f"Unsupported file_type: {file_type!r} (expected 'png' or 'jpg')")
        self.file_type = file_type

    async def exists(self, roi_id: str) -> bool:
        return await self.dd.image_exists(roi_id)

    async def get(self, roi_id: str) -> bytes:
        image = await self.dd.read_image(roi_id)
        image_data = BytesIO()
        fmt = "JPEG" if self.file_type == "jpg" else "PNG"
        image.save(image_data, format=fmt)
        return image_data.getvalue()
