"""Shared data models for scan findings and cleaning risk levels.

RiskLevel is the single most important type in this codebase: it's what
stands between "unused cache file" and "someone's irreplaceable photos".
Every category in cleaner_engine.CATEGORY_RULES must be reviewed for its
risk level before anything is added to it.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class RiskLevel(enum.IntEnum):
    SAFE = 0                 # e.g. package manager cache of superseded versions
    PROBABLY_SAFE = 1        # e.g. thumbnail cache, browser cache
    NEEDS_CONFIRMATION = 2   # e.g. leftover config of a removed app
    DANGEROUS = 3            # never auto-selected; requires explicit per-item opt-in

    @property
    def label(self) -> str:
        return {
            RiskLevel.SAFE: "Safe",
            RiskLevel.PROBABLY_SAFE: "Probably Safe",
            RiskLevel.NEEDS_CONFIRMATION: "Needs Confirmation",
            RiskLevel.DANGEROUS: "Dangerous",
        }[self]


@dataclass
class Finding:
    """One item a scanner discovered that the cleaner could potentially remove."""

    path: Path
    category: str                 # e.g. "package_cache", "thumbnail_cache", "app_leftover"
    risk: RiskLevel
    size_bytes: int
    reason: str                   # human-readable explanation shown in the UI
    is_directory: bool = False
    selected: bool = False        # UI checkbox state, defaults unchecked for anything
                                   # above SAFE risk — see cleaner_engine.default_selection()


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    scanned_paths: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_reclaimable_bytes(self) -> int:
        return sum(f.size_bytes for f in self.findings)

    def by_category(self) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = {}
        for f in self.findings:
            grouped.setdefault(f.category, []).append(f)
        return grouped
