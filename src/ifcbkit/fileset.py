"""
IFCB fileset discovery, validation, and data directory traversal.

Both sync and async APIs for finding IFCB data on the filesystem:
- list_filesets: generator yielding (dir, basename) for complete .hdr/.adc/.roi triplets
- find_fileset: recursive search for a specific bin by PID
- list_data_dirs: directories containing .hdr files
- Path validation with configurable include/exclude filters
"""

import asyncio
import os
from datetime import timezone

import aiofiles.os as aios
import aiofiles.ospath as aiopath

from .identifiers import parse_roi_id, bin_timestamp, bin_instrument_id


DEFAULT_EXCLUDE = ['skip', 'beads']
DEFAULT_INCLUDE = ['data']

# Corrected ("modified") ADC files live in a directory named ``adcmod`` that is
# a sibling of the raw data root directory, laid out as
# ``adcmod/<day>/<pid>.adc.mod`` and byte-compatible with the raw ``.adc``.
# Most datasets have no such sibling.
ADCMOD_DIR = 'adcmod'
ADCMOD_EXT = '.adc.mod'


def _adcmod_path(fileset_dir, pid, root_path):
    """Return the path a corrected ADC file would have for this fileset.

    The ``adcmod`` directory is strictly a sibling of ``root_path``. The day
    subdirectory name is the fileset's own containing directory name.

    :param fileset_dir: directory containing the raw fileset
    :param pid: the bin ID
    :param root_path: the raw data root directory
    """
    day = os.path.basename(os.path.normpath(fileset_dir))
    adcmod_root = os.path.join(
        os.path.dirname(os.path.abspath(root_path)), ADCMOD_DIR)
    return os.path.join(adcmod_root, day, pid + ADCMOD_EXT)


def sync_resolve_adc_path(fileset_dir, pid, root_path):
    """Return a corrected ``.adc.mod`` path if present, else the raw ``.adc``."""
    cand = _adcmod_path(fileset_dir, pid, root_path)
    if os.path.exists(cand):
        return cand
    return os.path.join(fileset_dir, pid + '.adc')


async def async_resolve_adc_path(fileset_dir, pid, root_path):
    """Return a corrected ``.adc.mod`` path if present, else the raw ``.adc``."""
    cand = _adcmod_path(fileset_dir, pid, root_path)
    if await aiopath.exists(cand):
        return cand
    return os.path.join(fileset_dir, pid + '.adc')


def validate_path(
    filepath,
    exclude=DEFAULT_EXCLUDE,
    include=DEFAULT_INCLUDE,
):
    """
    Validate an IFCB raw data file path.

    A well-formed raw data file path relative to some root only contains
    path components that are not excluded and are either included or part
    of the file's basename (without extension).

    :param filepath: the pathname of the file
    :param exclude: directory names to ignore
    :param include: directory names to include, even if they do not match
      the path's basename
    :returns: True if the pathname is valid
    """
    if not set(exclude).isdisjoint(set(include)):
        raise ValueError('include and exclude must be disjoint')

    dirname, basename = os.path.split(filepath)
    pid, ext = os.path.splitext(basename)
    components = dirname.split(os.sep)
    for c in components:
        if c in exclude:
            return False
        if c not in include and c not in pid:
            return False
    return True


# --- Fileset filtering: timestamp range / instrument ---

def _normalize_filter_time(dt):
    """Assume UTC for naive datetimes; leave aware datetimes untouched."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def make_fileset_filter(start_time=None, end_time=None, instrument=None):
    """
    Build a predicate ``(basename) -> bool`` for filtering filesets.

    :param start_time: inclusive lower bound (datetime); naive treated as UTC
    :param end_time: exclusive upper bound (datetime); naive treated as UTC
    :param instrument: instrument ID (int or str) or iterable of instrument IDs
    :returns: a predicate accepting a bin ID basename, or None if no filter is
      active. Basenames that fail to parse are excluded when any filter is set.
    :raises ValueError: if ``instrument`` cannot be coerced to int(s)

    The timestamp range is half-open ``[start_time, end_time)``.
    """
    if start_time is None and end_time is None and instrument is None:
        return None

    start = _normalize_filter_time(start_time)
    end = _normalize_filter_time(end_time)

    if instrument is None:
        instruments = None
    else:
        # Coerce scalars (int, or str like "127") and iterables of IDs to a set
        # of ints. Anything that won't coerce is a ValueError.
        scalars = (int, str) if not isinstance(instrument, bool) else ()
        values = [instrument] if isinstance(instrument, scalars) else instrument
        try:
            instruments = {int(v) for v in values}
        except (TypeError, ValueError) as e:
            raise ValueError(f'invalid instrument filter: {instrument!r}') from e

    def _pred(basename):
        try:
            if instruments is not None and bin_instrument_id(basename) not in instruments:
                return False
            if start is not None or end is not None:
                ts = bin_timestamp(basename)
                if start is not None and ts < start:
                    return False
                if end is not None and ts >= end:
                    return False
        except ValueError:
            return False
        return True

    return _pred


# --- Internal helpers: directory entry splitting ---

async def _async_split_dir_entries(dirpath, *, exclude=DEFAULT_EXCLUDE, sort=True, reverse=False):
    """Return (dirnames, filenames) for dirpath using aiofiles/os.path."""
    names = await aios.listdir(dirpath)
    dirnames, filenames = [], []

    async def _isdir(name):
        return await aiopath.isdir(os.path.join(dirpath, name))

    isdirs = await asyncio.gather(*(_isdir(n) for n in names))
    for name, is_dir in zip(names, isdirs):
        if is_dir:
            if name in exclude:
                continue
            dirnames.append(name)
        else:
            filenames.append(name)

    if sort:
        dirnames.sort(reverse=reverse)
        filenames.sort(reverse=reverse)
    return dirnames, filenames


def _sync_split_dir_entries(dirpath, *, exclude=DEFAULT_EXCLUDE, sort=True, reverse=False):
    """Return (dirnames, filenames) for dirpath using synchronous os calls."""
    names = os.listdir(dirpath)
    dirnames, filenames = [], []

    for name in names:
        if os.path.isdir(os.path.join(dirpath, name)):
            if name in exclude:
                continue
            dirnames.append(name)
        else:
            filenames.append(name)

    if sort:
        dirnames.sort(reverse=reverse)
        filenames.sort(reverse=reverse)
    return dirnames, filenames


# --- Fileset listing ---

async def async_list_filesets(
    dirpath,
    exclude=DEFAULT_EXCLUDE,
    include=DEFAULT_INCLUDE,
    sort=True,
    validate=True,
    require_adc=True,
    require_roi=True,
    start_time=None,
    end_time=None,
    instrument=None,
):
    """
    Async generator yielding (dp, basename) for each .hdr/.adc/(.roi) fileset found.

    :param dirpath: root directory to search
    :param exclude: directory names to skip
    :param include: directory names to always enter
    :param sort: whether to sort entries
    :param validate: whether to validate paths
    :param require_adc: require .adc file presence
    :param require_roi: require .roi file presence
    :param start_time: inclusive lower bound on bin timestamp (datetime, UTC if naive)
    :param end_time: exclusive upper bound on bin timestamp (datetime, UTC if naive)
    :param instrument: instrument ID (int) or iterable of instrument IDs to keep
    """
    if not set(exclude).isdisjoint(set(include)):
        raise ValueError('include and exclude must be disjoint')

    fs_filter = make_fileset_filter(start_time, end_time, instrument)

    stack = [dirpath]
    while stack:
        dp = stack.pop()
        dirnames, filenames = await _async_split_dir_entries(dp, exclude=exclude, sort=sort, reverse=True)

        for d in dirnames:
            stack.append(os.path.join(dp, d))

        fnset = set(filenames)
        for f in filenames:
            basename, extension = f[:-4], f[-3:]
            has_adc = (basename + '.adc') in fnset
            has_roi = (basename + '.roi') in fnset
            if extension == 'hdr' and (has_adc or not require_adc) and (has_roi or not require_roi):
                if validate:
                    if dp == dirpath:
                        reldir = ''
                    else:
                        reldir = dp[len(dirpath) + 1:]
                    if not validate_path(os.path.join(reldir, basename), include=include, exclude=exclude):
                        continue
                if fs_filter is not None and not fs_filter(basename):
                    continue
                yield dp, basename


def sync_list_filesets(
    dirpath,
    exclude=DEFAULT_EXCLUDE,
    include=DEFAULT_INCLUDE,
    sort=True,
    validate=True,
    require_adc=True,
    require_roi=True,
    start_time=None,
    end_time=None,
    instrument=None,
):
    """
    Sync generator yielding (dp, basename) for each .hdr/.adc/(.roi) fileset found.

    :param dirpath: root directory to search
    :param exclude: directory names to skip
    :param include: directory names to always enter
    :param sort: whether to sort entries
    :param validate: whether to validate paths
    :param require_adc: require .adc file presence
    :param require_roi: require .roi file presence
    :param start_time: inclusive lower bound on bin timestamp (datetime, UTC if naive)
    :param end_time: exclusive upper bound on bin timestamp (datetime, UTC if naive)
    :param instrument: instrument ID (int) or iterable of instrument IDs to keep
    """
    if not set(exclude).isdisjoint(set(include)):
        raise ValueError('include and exclude must be disjoint')

    fs_filter = make_fileset_filter(start_time, end_time, instrument)

    stack = [dirpath]
    while stack:
        dp = stack.pop()
        dirnames, filenames = _sync_split_dir_entries(dp, exclude=exclude, sort=sort, reverse=True)

        for d in dirnames:
            stack.append(os.path.join(dp, d))

        fnset = set(filenames)
        for f in filenames:
            basename, extension = f[:-4], f[-3:]
            has_adc = (basename + '.adc') in fnset
            has_roi = (basename + '.roi') in fnset
            if extension == 'hdr' and (has_adc or not require_adc) and (has_roi or not require_roi):
                if validate:
                    if dp == dirpath:
                        reldir = ''
                    else:
                        reldir = dp[len(dirpath) + 1:]
                    if not validate_path(os.path.join(reldir, basename), include=include, exclude=exclude):
                        continue
                if fs_filter is not None and not fs_filter(basename):
                    continue
                yield dp, basename


# --- Data directory listing ---

async def async_list_data_dirs(dirpath, exclude=DEFAULT_EXCLUDE, sort=True, prune=True):
    """
    Async generator yielding descendant directories that contain at least one .hdr file.

    :param dirpath: root directory to search
    :param exclude: directory names to skip
    :param sort: whether to sort entries
    :param prune: if True, stop descending once .hdr files are found
    """
    dirnames, filenames = await _async_split_dir_entries(dirpath, exclude=exclude, sort=sort, reverse=False)

    for name in filenames:
        if name[-3:] == 'hdr':
            yield dirpath
            if prune:
                return
            break

    for name in dirnames:
        child = os.path.join(dirpath, name)
        async for dd in async_list_data_dirs(child, exclude=exclude, sort=sort, prune=prune):
            yield dd


def sync_list_data_dirs(dirpath, exclude=DEFAULT_EXCLUDE, sort=True, prune=True):
    """
    Sync generator yielding descendant directories that contain at least one .hdr file.

    :param dirpath: root directory to search
    :param exclude: directory names to skip
    :param sort: whether to sort entries
    :param prune: if True, stop descending once .hdr files are found
    """
    dirnames, filenames = _sync_split_dir_entries(dirpath, exclude=exclude, sort=sort, reverse=False)

    for name in filenames:
        if name[-3:] == 'hdr':
            yield dirpath
            if prune:
                return
            break

    for name in dirnames:
        child = os.path.join(dirpath, name)
        for dd in sync_list_data_dirs(child, exclude=exclude, sort=sort, prune=prune):
            yield dd


# --- Find specific fileset ---

async def async_find_fileset(
    dirpath,
    pid,
    include=DEFAULT_INCLUDE,
    exclude=DEFAULT_EXCLUDE,
    require_adc=True,
    require_roi=True,
):
    """
    Async recursive search for a specific fileset by PID.

    :param dirpath: root directory to search
    :param pid: the bin ID to find
    :returns: basepath (without extension) or None
    """
    try:
        names = await aios.listdir(dirpath)
    except FileNotFoundError:
        return None

    # check direct match first
    hdr_name = pid + '.hdr'
    if hdr_name in names:
        basepath = os.path.join(dirpath, pid)
        if require_adc and (pid + '.adc') not in names:
            return None
        if require_roi and (pid + '.roi') not in names:
            return None
        return basepath

    # recurse into plausible subdirectories
    for name in names:
        if name in exclude:
            continue
        if name in include or name in pid:
            child = os.path.join(dirpath, name)
            if await aiopath.isdir(child):
                fs = await async_find_fileset(
                    child, pid,
                    include=include, exclude=exclude,
                    require_adc=require_adc, require_roi=require_roi,
                )
                if fs is not None:
                    return fs
    return None


def sync_find_fileset(
    dirpath,
    pid,
    include=DEFAULT_INCLUDE,
    exclude=DEFAULT_EXCLUDE,
    require_adc=True,
    require_roi=True,
):
    """
    Sync recursive search for a specific fileset by PID.

    :param dirpath: root directory to search
    :param pid: the bin ID to find
    :returns: basepath (without extension) or None
    """
    try:
        names = os.listdir(dirpath)
    except FileNotFoundError:
        return None

    # check direct match first
    hdr_name = pid + '.hdr'
    if hdr_name in names:
        basepath = os.path.join(dirpath, pid)
        if require_adc and (pid + '.adc') not in names:
            return None
        if require_roi and (pid + '.roi') not in names:
            return None
        return basepath

    # recurse into plausible subdirectories
    for name in names:
        if name in exclude:
            continue
        if name in include or name in pid:
            child = os.path.join(dirpath, name)
            if os.path.isdir(child):
                fs = sync_find_fileset(
                    child, pid,
                    include=include, exclude=exclude,
                    require_adc=require_adc, require_roi=require_roi,
                )
                if fs is not None:
                    return fs
    return None


# --- Data directory classes ---

class SyncIfcbDataDirectory:
    """Synchronous representation of an IFCB data directory.

    Provides dict-like access to IFCB filesets: exists, paths, list,
    list_images, read_images, read_image.

    :param root_path: the root directory containing IFCB filesets
    :param include: list of directory names to include when searching
    :param exclude: list of directory names to exclude when searching
    :param require_adc: if True, only consider filesets with .adc files
    :param require_roi: if True, only consider filesets with .roi files
    """

    def __init__(
        self,
        root_path,
        include=DEFAULT_INCLUDE,
        exclude=DEFAULT_EXCLUDE,
        require_adc=True,
        require_roi=True,
    ):
        self.root_path = root_path
        self.include = include
        self.exclude = exclude
        self.require_adc = require_adc
        self.require_roi = require_roi

        if not set(exclude).isdisjoint(set(include)):
            raise ValueError('include and exclude must be disjoint')
        if require_roi and not require_adc:
            raise ValueError('require_roi=True requires require_adc=True')

    def _exists(self, pid):
        fs = sync_find_fileset(
            self.root_path, pid,
            include=self.include, exclude=self.exclude,
            require_adc=self.require_adc, require_roi=self.require_roi,
        )
        if fs is None:
            return False, None
        return True, fs

    def exists(self, pid):
        """Return True if the fileset for the given PID exists."""
        exists, _ = self._exists(pid)
        return exists

    def paths(self, pid):
        """Return dict of file paths for the given PID."""
        exists, fs = self._exists(pid)
        if not exists:
            raise KeyError(pid)
        adc = None
        if self.require_adc:
            adc = sync_resolve_adc_path(os.path.dirname(fs), os.path.basename(fs), self.root_path)
        return {
            'hdr': fs + '.hdr',
            'adc': adc,
            'roi': fs + '.roi' if self.require_roi else None,
        }

    def list(self, start_time=None, end_time=None, instrument=None):
        """Yield dicts of {pid, hdr, adc, roi} for all filesets.

        :param start_time: inclusive lower bound on bin timestamp (UTC if naive)
        :param end_time: exclusive upper bound on bin timestamp (UTC if naive)
        :param instrument: instrument ID (int) or iterable of instrument IDs
        """
        for dp, bn in sync_list_filesets(
            self.root_path,
            exclude=self.exclude, include=self.include,
            require_adc=self.require_adc, require_roi=self.require_roi,
            start_time=start_time, end_time=end_time, instrument=instrument,
        ):
            yield {
                'pid': bn,
                'hdr': os.path.join(dp, bn + '.hdr'),
                'adc': sync_resolve_adc_path(dp, bn, self.root_path) if self.require_adc else None,
                'roi': os.path.join(dp, bn + '.roi') if self.require_roi else None,
            }

    def list_images(self, pid):
        """List ROI image metadata from the .adc file for the given PID."""
        from .adc import parse_adc_bytes
        paths = self.paths(pid)
        with open(paths['adc'], 'rb') as adc_file:
            return parse_adc_bytes(pid, adc_file.read())

    def read_images(self, pid, rois=None):
        """Read ROI images as PIL Images, with auto-stitching for I-style bins.

        Returns a BinImages (Mapping[int, Image]) with stitched I-style
        pairs. If rois is specified, returns a plain dict subset.
        """
        if not self.require_roi:
            raise ValueError('require_roi must be True to read ROI images')
        from .stitching import bin_images
        paths = self.paths(pid)
        with open(paths['adc'], 'rb') as f:
            adc_bytes = f.read()
        with open(paths['roi'], 'rb') as f:
            roi_bytes = f.read()
        images = bin_images(pid, adc_bytes, roi_bytes)
        if rois is not None:
            return {t: images[t] for t in rois if t in images}
        return images

    def read_image(self, roi_id):
        """Read a single ROI image by its ROI ID."""
        bin_id, target_num = parse_roi_id(roi_id)
        images = self.read_images(bin_id, rois={target_num})
        if target_num not in images:
            raise KeyError(roi_id)
        return images[target_num]


class AsyncIfcbDataDirectory:
    """Async representation of an IFCB data directory.

    Provides async versions of exists, paths, list, list_images,
    read_images, read_image.

    :param root_path: the root directory containing IFCB filesets
    :param include: list of directory names to include when searching
    :param exclude: list of directory names to exclude when searching
    :param require_adc: if True, only consider filesets with .adc files
    :param require_roi: if True, only consider filesets with .roi files
    """

    def __init__(
        self,
        root_path,
        include=DEFAULT_INCLUDE,
        exclude=DEFAULT_EXCLUDE,
        require_adc=True,
        require_roi=True,
    ):
        self.root_path = root_path
        self.include = include
        self.exclude = exclude
        self.require_adc = require_adc
        self.require_roi = require_roi

        if not set(exclude).isdisjoint(set(include)):
            raise ValueError('include and exclude must be disjoint')
        if require_roi and not require_adc:
            raise ValueError('require_roi=True requires require_adc=True')

    async def _exists(self, pid):
        fs = await async_find_fileset(
            self.root_path, pid,
            include=self.include, exclude=self.exclude,
            require_adc=self.require_adc, require_roi=self.require_roi,
        )
        if fs is None:
            return False, None
        return True, fs

    async def exists(self, pid):
        """Return True if the fileset for the given PID exists."""
        exists, _ = await self._exists(pid)
        return exists

    async def paths(self, pid):
        """Return dict of file paths for the given PID."""
        exists, fs = await self._exists(pid)
        if not exists:
            raise KeyError(pid)
        adc = None
        if self.require_adc:
            adc = await async_resolve_adc_path(os.path.dirname(fs), os.path.basename(fs), self.root_path)
        return {
            'hdr': fs + '.hdr',
            'adc': adc,
            'roi': fs + '.roi' if self.require_roi else None,
        }

    async def list(self, start_time=None, end_time=None, instrument=None):
        """Async generator yielding dicts of {pid, hdr, adc, roi} for all filesets.

        :param start_time: inclusive lower bound on bin timestamp (UTC if naive)
        :param end_time: exclusive upper bound on bin timestamp (UTC if naive)
        :param instrument: instrument ID (int) or iterable of instrument IDs
        """
        async for dp, bn in async_list_filesets(
            self.root_path,
            exclude=self.exclude, include=self.include,
            require_adc=self.require_adc, require_roi=self.require_roi,
            start_time=start_time, end_time=end_time, instrument=instrument,
        ):
            adc = None
            if self.require_adc:
                adc = await async_resolve_adc_path(dp, bn, self.root_path)
            yield {
                'pid': bn,
                'hdr': os.path.join(dp, bn + '.hdr'),
                'adc': adc,
                'roi': os.path.join(dp, bn + '.roi') if self.require_roi else None,
            }

    async def list_images(self, pid):
        """List ROI image metadata from the .adc file for the given PID."""
        import aiofiles
        from .adc import parse_adc_bytes
        paths = await self.paths(pid)
        async with aiofiles.open(paths['adc'], 'rb') as adc_file:
            adc_bytes = await adc_file.read()
        return parse_adc_bytes(pid, adc_bytes)

    async def images_exist(self, pid, roi_ids):
        """Check if the specified ROI IDs exist in the fileset."""
        images = await self.list_images(pid)
        existing_roi_ids = {img['roi_id'] for img in images.values()}
        return {roi_id: (roi_id in existing_roi_ids) for roi_id in roi_ids}

    async def image_exists(self, roi_id):
        """Check if the specified ROI ID exists."""
        bin_id, _ = parse_roi_id(roi_id)
        exists = await self.images_exist(bin_id, [roi_id])
        return exists[roi_id]

    async def read_images(self, pid, rois=None):
        """Read ROI images as PIL Images, with auto-stitching for I-style bins.

        Returns a BinImages (Mapping[int, Image]) with stitched I-style
        pairs. If rois is specified, returns a plain dict subset.
        """
        if not self.require_roi:
            raise ValueError('require_roi must be True to read ROI images')
        import aiofiles
        from .stitching import bin_images
        paths = await self.paths(pid)
        async with aiofiles.open(paths['adc'], 'rb') as f:
            adc_bytes = await f.read()
        async with aiofiles.open(paths['roi'], 'rb') as f:
            roi_bytes = await f.read()
        images = await asyncio.to_thread(bin_images, pid, adc_bytes, roi_bytes)
        if rois is not None:
            return {t: images[t] for t in rois if t in images}
        return images

    async def read_image(self, roi_id):
        """Read a single ROI image by its ROI ID."""
        bin_id, target_num = parse_roi_id(roi_id)
        images = await self.read_images(bin_id, rois={target_num})
        if target_num not in images:
            raise KeyError(roi_id)
        return images[target_num]
