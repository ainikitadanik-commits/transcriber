from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


class RealtimeSessionJournal:
    """Durable metadata and append-only committed-segment storage."""

    def __init__(self, sessions_dir: Path, session_id: str) -> None:
        self.session_id = session_id
        self.directory = sessions_dir / session_id
        self.metadata_path = self.directory / "session.json"
        self.segments_path = self.directory / "segments.jsonl"

    def create(self, metadata: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=False)
        self.segments_path.touch()
        self.update_metadata(metadata)

    def update_metadata(self, values: dict[str, Any]) -> None:
        current = self.metadata() if self.metadata_path.exists() else {}
        current.update(values)
        encoded = json.dumps(current, ensure_ascii=False, indent=2).encode("utf-8")
        temporary = self.metadata_path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.metadata_path)
        directory_fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def append(self, segments: Iterable[dict[str, Any]]) -> None:
        rows = [
            json.dumps(segment, ensure_ascii=False, separators=(",", ":")) + "\n"
            for segment in segments
        ]
        if not rows:
            return
        with self.segments_path.open("a", encoding="utf-8") as stream:
            stream.writelines(rows)
            stream.flush()
            os.fsync(stream.fileno())

    def metadata(self) -> dict[str, Any]:
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def load_segments(self) -> list[dict[str, Any]]:
        if not self.segments_path.exists():
            return []
        result = []
        lines = self.segments_path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                if index != len(lines) - 1:
                    raise
                # A crash can interrupt the final append; previous fsynced
                # records are still complete and recoverable.
                break
        return result


def find_recoverable_sessions(sessions_dir: Path) -> list[dict[str, Any]]:
    if not sessions_dir.is_dir():
        return []
    result = []
    for directory in sessions_dir.iterdir():
        if not directory.is_dir():
            continue
        journal = RealtimeSessionJournal(sessions_dir, directory.name)
        try:
            metadata = journal.metadata()
            if metadata.get("completed_at"):
                continue
            segment_count = len(journal.load_segments())
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if segment_count:
            result.append(
                {
                    "session_id": directory.name,
                    "started_at": metadata.get("started_at"),
                    "segment_count": segment_count,
                }
            )
    return sorted(result, key=lambda item: item.get("started_at") or "", reverse=True)
