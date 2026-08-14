"""
``ifcbkit-qc`` — run the QC checks from a shell.

Takes bins or whole data trees, prints a grouped summary (or JSON Lines with
``--json``), and exits non-zero when something is wrong so it can be used in a
pipeline:

- ``0`` nothing of ``error`` severity (``--strict``: nor ``warning``)
- ``1`` at least one such finding
- ``2`` QC itself could not run
"""

import argparse
import os
import sys

from . import check_bin
from .collection import check_collection, list_bins
from .model import Cost, Report, Severity
from .products import PRODUCTS
from .registry import CHECKS, GROUPS, codes_for_group

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_FAILED = 2

_SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for ``ifcbkit-qc``."""
    parser = argparse.ArgumentParser(
        prog='ifcbkit-qc',
        description='Check IFCB raw data and products for integrity.')
    parser.add_argument(
        'paths', nargs='*', metavar='PATH',
        help='a bin (basepath, .hdr/.adc/.roi, or bin directory) or a data tree')
    parser.add_argument(
        '--cost', choices=[c.value for c in Cost], default=Cost.PARSE.value,
        help='how much I/O to spend per bin (default: %(default)s)')
    parser.add_argument(
        '--json', action='store_true',
        help='emit JSON Lines, one finding per line')
    parser.add_argument(
        '--expect', default='',
        help=f'comma-separated products that must be present: '
             f'{", ".join(PRODUCTS)}')
    parser.add_argument(
        '--products-root', metavar='PATH',
        help='where products live (default: each bin\'s own directory). '
             'Searched by day/year convention, then recursively.')
    parser.add_argument(
        '--product-dir', metavar='TYPE=PATH', action='append', default=[],
        help=f'root directory for one product type ({", ".join(PRODUCTS)}); '
             f'repeatable. This is the usual layout: one tree per product type')
    parser.add_argument(
        '--no-product-search', action='store_true',
        help='do not fall back to a recursive walk of a product root; rely on '
             'the day/year directory conventions only')
    parser.add_argument(
        '--adcmod-root', metavar='PATH',
        help='adcmod tree to check for orphaned corrections')
    parser.add_argument(
        '--root', metavar='PATH',
        help='raw data root, used to locate the sibling adcmod tree per bin')
    parser.add_argument(
        '--only', default='', metavar='CODE,...',
        help='report only these check codes')
    parser.add_argument(
        '--ignore', default='', metavar='CODE,...',
        help='suppress these check codes')
    parser.add_argument(
        '--mixed-instruments', action='store_true',
        help='run the opt-in mixed_instruments check')
    parser.add_argument(
        '--strict', action='store_true',
        help='count warnings toward a non-zero exit status')
    parser.add_argument(
        '--list-checks', action='store_true',
        help='list every check code with its severity and cost, then exit')
    return parser


def _split_codes(value: str) -> set:
    return {code.strip() for code in value.split(',') if code.strip()}


def _validate_codes(codes, label) -> None:
    unknown = sorted(codes - set(CHECKS))
    if unknown:
        raise ValueError(f'unknown check code(s) for {label}: {", ".join(unknown)}')


def list_checks(out) -> None:
    """Print the whole registry, grouped."""
    for group in GROUPS:
        print(f'{group}:', file=out)
        for code in codes_for_group(group):
            spec = CHECKS[code]
            opt_in = ' [opt-in]' if spec.opt_in else ''
            print(f'  {code:<34} {spec.severity.value:<8} {spec.cost.value:<6}'
                  f' {spec.summary}{opt_in}', file=out)


def _is_fileset(path: str) -> bool:
    """True if this path names one bin rather than a tree to walk."""
    if os.path.isdir(path):
        basename = os.path.basename(os.path.normpath(path))
        return os.path.exists(os.path.join(path, basename + '.adc')) or \
            os.path.exists(os.path.join(path, basename + '.hdr'))
    return True


def _parse_product_dirs(specs) -> dict:
    """Turn ``TYPE=PATH`` arguments into a ``{product: directory}`` mapping."""
    product_dirs = {}
    for spec in specs:
        product, _, directory = spec.partition('=')
        if product not in PRODUCTS or not directory:
            raise ValueError(
                f'--product-dir expects TYPE=PATH with TYPE in '
                f'{", ".join(PRODUCTS)}, got: {spec}')
        product_dirs[product] = directory
    return product_dirs


def _reports_for_path(path, args, expect, product_dirs) -> list:
    """Run the right checks for one command-line path."""
    cost = Cost(args.cost)
    product_options = dict(
        products_dir=args.products_root, product_dirs=product_dirs,
        product_search=not args.no_product_search)
    if _is_fileset(path):
        return [check_bin(
            path, cost=cost, expect=expect, root_path=args.root,
            **product_options)]

    reports = [check_collection(
        path, mixed_instruments=args.mixed_instruments,
        adcmod_root=args.adcmod_root)]
    for directory, bin_id in list_bins(path):
        reports.append(check_bin(
            os.path.join(directory, bin_id), cost=cost, expect=expect,
            root_path=args.root or path, **product_options))
    return reports


def _filter(report: Report, only, ignore) -> Report:
    """Return a copy of the report with only/ignore applied."""
    if not only and not ignore:
        return report
    filtered = Report(
        subject=report.subject, cost=report.cost, skipped=report.skipped,
        truncated=report.truncated, max_per_code=report.max_per_code)
    for finding in report.findings:
        if only and finding.code not in only:
            continue
        if finding.code in ignore:
            continue
        filtered.findings.append(finding)
    return filtered


def _print_report(report: Report, out) -> None:
    """Print one report as a grouped, human-readable block."""
    counts = report.counts_by_severity()
    headline = ', '.join(
        f'{counts[severity]} {severity.value}'
        for severity in _SEVERITY_ORDER if counts[severity])
    print(f'{report.subject}: {headline or "no findings"}', file=out)
    for severity in _SEVERITY_ORDER:
        for finding in report.findings:
            if finding.severity is severity:
                print(f'  {severity.value:<8} {finding.code:<34} '
                      f'{finding.message}', file=out)
    for code, suppressed in sorted(report.truncated.items()):
        print(f'  ...      {code:<34} and {suppressed} more not listed',
              file=out)
    for code, reason in sorted(report.skipped.items()):
        print(f'  skipped  {code:<34} {reason}', file=out)


def main(argv=None) -> int:
    """Entry point for ``ifcbkit-qc``. Returns the process exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    out = sys.stdout

    if args.list_checks:
        list_checks(out)
        return EXIT_OK
    if not args.paths:
        parser.error('at least one PATH is required (or --list-checks)')

    try:
        only = _split_codes(args.only)
        ignore = _split_codes(args.ignore)
        _validate_codes(only, '--only')
        _validate_codes(ignore, '--ignore')
        expect = tuple(_split_codes(args.expect))
        unknown = [p for p in expect if p not in PRODUCTS]
        if unknown:
            raise ValueError(
                f'unknown product(s) for --expect: {", ".join(unknown)}')
        product_dirs = _parse_product_dirs(args.product_dir)

        reports = []
        for path in args.paths:
            if not os.path.exists(path) and not os.path.exists(path + '.adc'):
                raise FileNotFoundError(path)
            reports.extend(
                _reports_for_path(path, args, expect, product_dirs))
    except (ValueError, OSError) as e:
        print(f'ifcbkit-qc: {e}', file=sys.stderr)
        return EXIT_FAILED

    reports = [_filter(report, only, ignore) for report in reports]

    if args.json:
        for report in reports:
            out.write(report.to_jsonl())
    else:
        for report in reports:
            _print_report(report, out)
        n_bad = sum(1 for report in reports if not report.ok)
        print(f'{len(reports)} subject(s) checked, {n_bad} with errors',
              file=out)

    has_errors = any(report.errors for report in reports)
    has_warnings = any(report.warnings for report in reports)
    if has_errors or (args.strict and has_warnings):
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
