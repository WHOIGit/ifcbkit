"""
Quality control for IFCB data.

QC reports whether data is **intact** — present, parseable, internally
consistent. It does not judge whether the data is scientifically *good*:
no ml_analyzed, no bead/blank detection, no trigger-rate plausibility, no
class-score distributions. Those are analysis, not integrity.

Findings carry a severity fixed by the check registry (``error`` = unusable,
``warning`` = usable but off, ``info`` = notable). Consumers filter by code to
set their own policy, which is why e.g. an empty bin is reported ``info`` here
even though ifcbdb treats it as bad.

Three entry points, by scope:

- :func:`ifcbkit.qc.raw.check_fileset` — one raw fileset
- :func:`ifcbkit.qc.products.check_products` — one bin's derived products
- :func:`ifcbkit.qc.collection.check_collection` — the shape of a whole tree

:func:`check_bin` runs the first two together, sharing one ADC parse.

Everything is sync. Async callers should run these in an executor rather than
having a second, parallel API surface to keep in step.
"""

from .collection import check_collection, list_bins, walk_filesets
from .model import (
    Cost,
    Finding,
    MAX_FINDINGS_PER_CODE,
    Report,
    Severity,
    cost_allows,
)
from .products import (
    candidate_directories,
    check_products,
    find_products,
    product_root,
)
from .raw import check_fileset, resolve_fileset
from .registry import CHECKS, CheckSpec, GROUPS, codes_for_group, spec_for

__all__ = [
    'CHECKS',
    'CheckSpec',
    'Cost',
    'Finding',
    'GROUPS',
    'MAX_FINDINGS_PER_CODE',
    'Report',
    'Severity',
    'candidate_directories',
    'check_bin',
    'check_collection',
    'check_fileset',
    'check_products',
    'codes_for_group',
    'cost_allows',
    'find_products',
    'list_bins',
    'product_root',
    'resolve_fileset',
    'spec_for',
    'walk_filesets',
]


def check_bin(path, *, bin_id=None, cost=Cost.PARSE, expect=(),
              root_path=None, adcmod=None, products_dir=None,
              product_dirs=None, product_search=True) -> Report:
    """Check one bin's raw fileset and its derived products together.

    The raw pass hands its parsed targets to the product pass, so product
    coverage is checked against the bin's real target set without parsing the
    ADC twice. "Real" means the corrected ADC's targets when ``root_path`` or
    ``adcmod`` puts a usable correction in play: that is the ADC consumers read
    and the one the products were derived from, so comparing products against
    the raw ADC instead would invent coverage findings.

    :param path: basepath, a .hdr/.adc/.roi path, or a bin-named directory
    :param bin_id: the bin ID, if it differs from the basename
    :param cost: I/O budget; see :class:`Cost`
    :param expect: products that must be present ('features', 'class', 'blobs')
    :param root_path: the raw data root, if corrected ADC files should be
      checked
    :param adcmod: an explicit .adc.mod path, instead of deriving one
    :param products_dir: where to look for products (default: the fileset's
      own directory). Products normally live in their own tree, so this or
      ``product_dirs`` is what a real archive needs.
    :param product_dirs: ``{product: directory}`` — a root per product type,
      the usual production layout
    :param product_search: fall back to a recursive walk of a product root;
      see :func:`ifcbkit.qc.products.find_products`
    :returns: one :class:`Report` covering both scopes
    """
    paths = resolve_fileset(path, bin_id)
    targets: list = []
    report = check_fileset(
        path, bin_id=bin_id, cost=cost, root_path=root_path, adcmod=adcmod,
        targets_out=targets)
    if products_dir is None and not product_dirs:
        products_dir = paths.directory
    check_products(
        products_dir, paths.bin_id, cost=cost, expect=expect,
        targets={record['target'] for record in targets} if targets else None,
        report=report, product_dirs=product_dirs, search=product_search)
    return report
