"""
Product file discovery for IFCB derived data (blobs, features, class scores).

Helpers for locating derived product files alongside raw data:
- find_product_file: recursive search
- list_product_files: pattern-matched listing
- Convenience: blob_path, class_scores_path, features_path

Both sync and async APIs are provided.
"""

import os
import re

import aiofiles.os as aios
import aiofiles.ospath as aiopath


# --- Async API ---

async def async_find_product_file(directory, filename, exhaustive=False):
    """Recursively search for a product file by name.

    :param directory: root directory to search
    :param filename: the filename to find
    :param exhaustive: if False, only recurse into directories whose name
        appears in the filename (faster). If True, search all subdirs.
    :returns: full path to the file, or None
    """
    candidate = os.path.join(directory, filename)
    if await aiopath.exists(candidate):
        return candidate

    try:
        names = await aios.listdir(directory)
    except FileNotFoundError:
        return None

    for name in names:
        path = os.path.join(directory, name)
        if await aiopath.isdir(path):
            if not exhaustive and name not in filename:
                continue
            result = await async_find_product_file(path, filename, exhaustive=exhaustive)
            if result is not None:
                return result
        elif name == filename:
            return path

    return None


async def async_list_product_files(directory, regex):
    """Async generator yielding paths to product files matching a regex.

    :param directory: root directory to search
    :param regex: regex pattern to match filenames against
    """
    try:
        names = await aios.listdir(directory)
    except FileNotFoundError:
        return

    for name in names:
        path = os.path.join(directory, name)
        if await aiopath.isdir(path):
            async for p in async_list_product_files(path, regex):
                yield p
        elif re.match(regex, name):
            yield path


async def async_product_path(directory, filename, exhaustive=False):
    """Find a product file or raise FileNotFoundError."""
    path = await async_find_product_file(directory, filename, exhaustive=exhaustive)
    if not path:
        raise FileNotFoundError(f'Product file {filename} not found in {directory}')
    return path


async def async_blob_path(directory, pid, version=4):
    """Find the blob ZIP file for a given PID."""
    filename = f'{pid}_blobs_v{version}.zip'
    return await async_product_path(directory, filename)


async def async_class_scores_path(directory, pid, version=4):
    """Find the class scores CSV file for a given PID."""
    filename = f'{pid}.csv'
    return await async_product_path(directory, filename)


async def async_features_path(directory, pid, version=4):
    """Find the features ZIP file for a given PID."""
    filename = f'{pid}_features_v{version}.zip'
    return await async_product_path(directory, filename)


# --- Sync API ---

def sync_find_product_file(directory, filename, exhaustive=False):
    """Recursively search for a product file by name (synchronous).

    :param directory: root directory to search
    :param filename: the filename to find
    :param exhaustive: if False, only recurse into directories whose name
        appears in the filename (faster). If True, search all subdirs.
    :returns: full path to the file, or None
    """
    candidate = os.path.join(directory, filename)
    if os.path.exists(candidate):
        return candidate

    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return None

    for name in names:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            if not exhaustive and name not in filename:
                continue
            result = sync_find_product_file(path, filename, exhaustive=exhaustive)
            if result is not None:
                return result
        elif name == filename:
            return path

    return None


def sync_list_product_files(directory, regex):
    """Generator yielding paths to product files matching a regex (synchronous).

    :param directory: root directory to search
    :param regex: regex pattern to match filenames against
    """
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return

    for name in names:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            yield from sync_list_product_files(path, regex)
        elif re.match(regex, name):
            yield path


def sync_product_path(directory, filename, exhaustive=False):
    """Find a product file or raise FileNotFoundError (synchronous)."""
    path = sync_find_product_file(directory, filename, exhaustive=exhaustive)
    if not path:
        raise FileNotFoundError(f'Product file {filename} not found in {directory}')
    return path


def sync_blob_path(directory, pid, version=4):
    """Find the blob ZIP file for a given PID (synchronous)."""
    filename = f'{pid}_blobs_v{version}.zip'
    return sync_product_path(directory, filename)


def sync_class_scores_path(directory, pid, version=4):
    """Find the class scores CSV file for a given PID (synchronous)."""
    filename = f'{pid}.csv'
    return sync_product_path(directory, filename)


def sync_features_path(directory, pid, version=4):
    """Find the features ZIP file for a given PID (synchronous)."""
    filename = f'{pid}_features_v{version}.zip'
    return sync_product_path(directory, filename)
