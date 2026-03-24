"""
Abstract base classes for IFCB data stores.

AsyncBinStore: async store for raw bin data files (.hdr, .adc, .roi)
AsyncRoiStore / SyncRoiStore: stores for rendered ROI images
"""

from abc import ABC, abstractmethod
import asyncio

from ..identifiers import add_target, parse_roi_id
from ..adc import parse_adc_bytes
from ..stitching import bin_images


class AsyncBinStore(ABC):
    """Async store for IFCB raw bin data files (.hdr, .adc, .roi).

    Keys are bin file basenames: '{bin_id}.{ext}',
    e.g. 'D20221227T093138_IFCB127.hdr'.
    """

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True if the given bin file exists."""
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Return the full content of the given bin file."""
        ...

    async def list_images(self, bin_id: str) -> dict:
        """Parse .adc to return ROI metadata dict."""
        adc_bytes = await self.get(f"{bin_id}.adc")
        return await asyncio.to_thread(parse_adc_bytes, bin_id, adc_bytes)

    async def read_images(self, bin_id: str, rois=None):
        """Extract PIL Images from .roi for this bin, with auto-stitching.

        Returns a BinImages (Mapping[int, Image]) with stitched I-style
        pairs. If rois is specified, returns a plain dict subset.
        """
        adc_bytes = await self.get(f"{bin_id}.adc")
        roi_bytes = await self.get(f"{bin_id}.roi")
        images = await asyncio.to_thread(bin_images, bin_id, adc_bytes, roi_bytes)
        if rois is not None:
            return {t: images[t] for t in rois if t in images}
        return images

    async def put(self, key: str, data: bytes) -> None:
        """Store the given bin file. Default raises NotImplementedError."""
        raise NotImplementedError("bin store is read-only")

    async def read_image(self, roi_id: str):
        """Extract a single PIL Image by ROI ID."""
        bin_id, target_num = parse_roi_id(roi_id)
        images = await self.read_images(bin_id, rois={target_num})
        if target_num not in images:
            raise KeyError(roi_id)
        return images[target_num]

    async def get_path(self, key: str) -> str | None:
        """Return the filesystem path for the given key, or None if unavailable.

        Only overridden by filesystem-backed stores; all others return None.
        """
        return None

    async def iter_images(self, bin_id: str, rois=None):
        """Async generator yielding (roi_id, PIL.Image) pairs.

        Default loads all images via read_images first; the filesystem store
        overrides this to stream one image at a time without holding them all
        in memory simultaneously.
        """
        images = await self.read_images(bin_id, rois=rois)
        for target_num, image in images.items():
            yield add_target(bin_id, target_num), image


class SyncRoiStore(ABC):
    """A synchronous store for IFCB ROI images."""

    @abstractmethod
    def get(self, roi_id: str) -> bytes:
        """Get the image data for the given ROI ID."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, roi_id: str) -> bool:
        """Check if the given ROI ID exists in the store."""
        raise NotImplementedError

    def put(self, roi_id: str, image_data: bytes):
        raise NotImplementedError("ROI store is read-only")


class AsyncRoiStore(ABC):
    """An asynchronous store for IFCB ROI images."""

    @abstractmethod
    async def get(self, roi_id: str) -> bytes:
        """Get the image data for the given ROI ID."""
        raise NotImplementedError

    @abstractmethod
    async def exists(self, roi_id: str) -> bool:
        """Check if the given ROI ID exists in the store."""
        raise NotImplementedError

    async def put(self, roi_id: str, image_data: bytes):
        raise NotImplementedError("ROI store is read-only")
