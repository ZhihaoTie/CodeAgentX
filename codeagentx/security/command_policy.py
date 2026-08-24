"""Heuristic command risk classification for shell tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class CommandRisk(Enum):
    SAFE = "safe"
    WRITE = "write"
    NETWORK = "network"
    DANGEROUS = "dangerous"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CommandClassification:
    command: str
    risk: CommandRisk
    reason: str
    matched_pattern: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "risk": self.risk.value,
            "reason": self.reason,
            "matched_pattern": self.matched_pattern,
        }


class CommandRiskClassifier:
    """Classifies shell commands before they reach BashTool.

    This is intentionally heuristic. It is a policy signal for permissions and
    audit metadata, not a complete shell parser or sandbox replacement.
    """

    DEFAULT_WRITE_PATTERNS = [
        ">",
        ">>",
        "| tee",
        "touch ",
        "mkdir ",
        "cp ",
        "copy ",
        "mv ",
        "move ",
        "rm ",
        "del ",
        "erase ",
        "rmdir ",
        "sed -i",
        "git add",
        "git commit",
        "git checkout",
        "git merge",
        "git rebase",
        "git reset ",
        "git clean",
    ]

    DEFAULT_NETWORK_PATTERNS = [
        "curl ",
        "wget ",
        "ssh ",
        "scp ",
        "sftp ",
        "rsync ",
        "git clone",
        "git pull",
        "git push",
        "git fetch",
        "pip install",
        "python -m pip install",
        "npm install",
        "npm i ",
        "pnpm install",
        "yarn add",
        "docker pull",
        "invoke-webrequest",
        "iwr ",
        "irm ",
    ]

    def __init__(
        self,
        *,
        allowed_prefixes: Iterable[str] = (),
        denied_patterns: Iterable[str] = (),
        write_patterns: Iterable[str] | None = None,
        network_patterns: Iterable[str] | None = None,
    ) -> None:
        self.allowed_prefixes = tuple(_normalize_pattern(item) for item in allowed_prefixes)
        self.denied_patterns = tuple(_normalize_pattern(item) for item in denied_patterns)
        self.write_patterns = tuple(
            _normalize_pattern(item)
            for item in (write_patterns if write_patterns is not None else self.DEFAULT_WRITE_PATTERNS)
        )
        self.network_patterns = tuple(
            _normalize_pattern(item)
            for item in (network_patterns if network_patterns is not None else self.DEFAULT_NETWORK_PATTERNS)
        )

    def classify(self, command: str) -> CommandClassification:
        raw_command = command or ""
        normalized = _normalize_command(raw_command)
        if not normalized:
            return CommandClassification(
                command=raw_command,
                risk=CommandRisk.UNKNOWN,
                reason="empty command",
            )

        denied = _first_contained(normalized, self.denied_patterns)
        if denied:
            return CommandClassification(
                command=raw_command,
                risk=CommandRisk.DANGEROUS,
                reason="command matches denied pattern",
                matched_pattern=denied,
            )

        network = _first_contained(normalized, self.network_patterns)
        if network:
            return CommandClassification(
                command=raw_command,
                risk=CommandRisk.NETWORK,
                reason="command may access the network or remote systems",
                matched_pattern=network,
            )

        write = _first_contained(normalized, self.write_patterns)
        if write:
            return CommandClassification(
                command=raw_command,
                risk=CommandRisk.WRITE,
                reason="command may modify local workspace state",
                matched_pattern=write,
            )

        allowed = _first_prefix(normalized, self.allowed_prefixes)
        if allowed:
            return CommandClassification(
                command=raw_command,
                risk=CommandRisk.SAFE,
                reason="command matches allowed read-only prefix",
                matched_pattern=allowed,
            )

        return CommandClassification(
            command=raw_command,
            risk=CommandRisk.UNKNOWN,
            reason="command did not match known safe, write, network, or dangerous patterns",
        )


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().casefold().split())


def _normalize_pattern(pattern: str) -> str:
    return " ".join(str(pattern).strip().casefold().split())


def _first_contained(command: str, patterns: Iterable[str]) -> str:
    for pattern in patterns:
        if pattern and pattern in command:
            return pattern
    return ""


def _first_prefix(command: str, prefixes: Iterable[str]) -> str:
    for prefix in prefixes:
        if not prefix:
            continue
        if command == prefix or command.startswith(prefix + " "):
            return prefix
    return ""
