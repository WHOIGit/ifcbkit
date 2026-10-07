"""
Data model for ifcbkit QC findings.

QC answers one question: **is this data intact?** It never answers "is this
data good?" — no analysis, no plausibility judgments about the science. The
library reports facts; the consumer sets policy. Zero ROIs is the canonical
example: reported as ``info``, because ifcbdb treats it as bad data and
ifcb-ingest treats it as a valid empty bin.
"""

import json
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """How bad a finding is.

    - ``ERROR``: malformed or missing; the data is unusable.
    - ``WARNING``: usable, but something is off.
    - ``INFO``: notable, not a defect.
    """

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


class Cost(str, Enum):
    """How much I/O a check is willing to do.

    - ``STAT``: filenames and ``os.stat`` only.
    - ``PARSE``: read the .hdr and .adc, stat the .roi (the default).
    - ``FULL``: decode ROI images, open product containers.
    """

    STAT = 'stat'
    PARSE = 'parse'
    FULL = 'full'


# Cost tiers in increasing order, for "is this check affordable" comparisons.
_COST_ORDER = {Cost.STAT: 0, Cost.PARSE: 1, Cost.FULL: 2}


def cost_allows(budget: Cost, required: Cost) -> bool:
    """Return True if a check requiring ``required`` I/O fits in ``budget``."""
    return _COST_ORDER[Cost(required)] <= _COST_ORDER[Cost(budget)]


# A badly damaged file can fail the same check on every line or every row.
# Findings past this many per code are counted rather than listed — counted,
# never silently dropped; see Report.truncated.
MAX_FINDINGS_PER_CODE = 50


@dataclass(frozen=True, slots=True)
class Finding:
    """One QC observation about one subject.

    :param code: registry key, e.g. ``'adc_blank_line'``
    :param severity: from the registry entry for ``code``
    :param subject: bin ID, or a directory path for collection-level checks
    :param message: rendered human-readable statement of the fact
    :param path: the specific file the finding is about, when applicable
    :param detail: structured specifics — line numbers, counts, deltas
    """

    code: str
    severity: Severity
    subject: str
    message: str
    path: str | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            'code': self.code,
            'severity': self.severity.value,
            'subject': self.subject,
            'message': self.message,
            'path': self.path,
            'detail': self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Finding':
        """Rebuild a Finding from :meth:`to_dict` output."""
        return cls(
            code=data['code'],
            severity=Severity(data['severity']),
            subject=data['subject'],
            message=data['message'],
            path=data.get('path'),
            detail=data.get('detail') or {},
        )

    def to_json(self) -> str:
        """Return a single-line JSON representation."""
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(slots=True)
class Report:
    """The findings for one subject, plus what was not checked.

    :param subject: what was checked — a bin ID or a directory path
    :param cost: the I/O budget the checks ran under
    :param findings: every finding, in the order the checks emitted them
    :param skipped: codes that could not be evaluated, mapped to the reason
      (an unaffordable cost tier is not "skipped" — those checks simply do
      not apply at that budget; this is for missing optional dependencies
      and unreadable inputs that block a whole group)
    :param truncated: ``{code: n_not_listed}`` for checks that fired more than
      ``max_per_code`` times
    :param max_per_code: how many findings to list per code before counting
    """

    subject: str
    cost: Cost
    findings: list[Finding] = field(default_factory=list)
    skipped: dict = field(default_factory=dict)
    truncated: dict = field(default_factory=dict)
    max_per_code: int = MAX_FINDINGS_PER_CODE
    _emitted: dict = field(default_factory=dict, repr=False)

    def add(self, finding: Finding) -> None:
        """Record a finding, capping how many of one code are listed.

        Past the cap the finding is counted in :attr:`truncated` instead of
        listed, so a report never claims a file is cleaner than it is.
        """
        seen = self._emitted.get(finding.code, 0)
        self._emitted[finding.code] = seen + 1
        if seen < self.max_per_code:
            self.findings.append(finding)
        else:
            self.truncated[finding.code] = seen + 1 - self.max_per_code

    def total_for(self, code: str) -> int:
        """Return how many times a code fired, listed or not."""
        return self._emitted.get(code, len(
            [f for f in self.findings if f.code == code]))

    @property
    def errors(self) -> list[Finding]:
        """Findings with ``ERROR`` severity."""
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        """Findings with ``WARNING`` severity."""
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def infos(self) -> list[Finding]:
        """Findings with ``INFO`` severity."""
        return [f for f in self.findings if f.severity is Severity.INFO]

    @property
    def ok(self) -> bool:
        """True if nothing of ``ERROR`` severity was found."""
        return not self.errors

    @property
    def codes(self) -> set:
        """The set of codes present in this report."""
        return {f.code for f in self.findings}

    def counts_by_code(self) -> dict:
        """Return ``{code: count}`` for the findings in this report."""
        counts: dict = {}
        for finding in self.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
        return counts

    def counts_by_severity(self) -> dict:
        """Return ``{severity: count}`` for the findings in this report."""
        counts = {s: 0 for s in Severity}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    def extend(self, other: 'Report') -> None:
        """Absorb another report's findings, skips, and truncation counts.

        Truncation counts are summed, not overwritten: two reports that each
        truncated the same code both had findings they did not list, and a
        merged report that kept only one of those counts would claim the data
        is cleaner than it is.
        """
        self.findings.extend(other.findings)
        self.skipped.update(other.skipped)
        for code, count in other.truncated.items():
            self.truncated[code] = self.truncated.get(code, 0) + count
        for code, count in other._emitted.items():
            self._emitted[code] = self._emitted.get(code, 0) + count

    def filtered(self, only=(), ignore=()) -> 'Report':
        """Return a copy with only/ignore code filters applied.

        Everything keyed by code is filtered together — findings, skips, and
        truncation counts — so the copy cannot report a skip or a truncation
        for a code whose findings it dropped. Nothing is shared with the
        original: mutating either afterwards leaves the other alone.

        :param only: if non-empty, keep only these codes
        :param ignore: drop these codes
        :returns: a new :class:`Report` with the same subject and cost
        """
        only = set(only)
        ignore = set(ignore)

        def keep(code: str) -> bool:
            if only and code not in only:
                return False
            return code not in ignore

        copy = Report(
            subject=self.subject,
            cost=self.cost,
            findings=[f for f in self.findings if keep(f.code)],
            skipped={code: reason for code, reason in self.skipped.items()
                     if keep(code)},
            truncated={code: count for code, count in self.truncated.items()
                       if keep(code)},
            max_per_code=self.max_per_code,
        )
        copy._emitted.update(
            {code: count for code, count in self._emitted.items()
             if keep(code)})
        return copy

    def envelope(self, *, omit_skipped=()) -> dict:
        """Return the per-report metadata record for :meth:`to_jsonl`.

        A findings-only stream cannot say that a subject was checked and found
        clean, and cannot say that a check was *skipped* rather than passed.
        Both read as health — the one direction an integrity report must never
        fail in — so this record carries them, along with the truncation counts
        that would otherwise make a badly damaged bin look mildly damaged.

        ``skipped`` and ``truncated`` are present only when non-empty, so the
        record for a clean subject stays short enough to scan a sweep of them.

        :param omit_skipped: codes to leave out of ``skipped`` because the
          caller reports them once for a whole run instead of per subject; see
          :func:`ifcbkit.qc.cli` for why that matters over many subjects
        """
        skipped = {code: reason for code, reason in self.skipped.items()
                   if code not in omit_skipped}
        record = {
            'type': 'report',
            'subject': self.subject,
            'cost': self.cost.value,
            'n_findings': len(self.findings),
            'n_errors': len(self.errors),
        }
        if skipped:
            record['skipped'] = skipped
        if self.truncated:
            record['truncated'] = dict(self.truncated)
        return record

    def to_jsonl(self, *, omit_skipped=()) -> str:
        """Return the whole report as JSON Lines.

        The first line is :meth:`envelope` (``type`` of ``report``), followed
        by one line per listed finding (``type`` of ``finding``). Every line
        carries ``type`` so a stream covering several subjects can be split by
        kind; a filter on a finding field, such as ``severity`` or ``code``,
        passes over envelopes on its own.

        Serializing only the findings would drop three of the five things a
        report knows — see :meth:`envelope`.

        :param omit_skipped: passed through to :meth:`envelope`
        """
        lines = [json.dumps(self.envelope(omit_skipped=omit_skipped),
                            sort_keys=True)]
        lines.extend(
            json.dumps({'type': 'finding', **finding.to_dict()}, sort_keys=True)
            for finding in self.findings)
        return ''.join(line + '\n' for line in lines)
