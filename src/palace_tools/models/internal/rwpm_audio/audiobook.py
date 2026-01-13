from __future__ import annotations

import sys
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from mutagen.mp3 import MP3

from palace_tools.models.api.rwpm_audiobook import Manifest, ToCEntry
from palace_tools.models.internal.rwpm_audio.audio_segment import (
    AudioSegment,
    audio_segments_for_all_toc_entries,
    audio_segments_for_toc_entry,
)

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class EnhancedToCEntry(ToCEntry):
    depth: int
    duration: int
    audio_segments: Sequence[AudioSegment]
    sub_entries: Sequence[EnhancedToCEntry]  # These are our enhanced children.

    actual_duration: float = 0.0

    @cached_property
    def total_duration(self) -> int:
        """The duration (in seconds) of this ToCEntry and its children."""
        return sum(toc.duration for toc in self.enhanced_toc_in_playback_order)

    @property
    def enhanced_toc_in_playback_order(self) -> Generator[EnhancedToCEntry]:
        """Iterator yielding all ToCEntries in the hierarchy, in the order they appear in the manifest."""
        yield self
        for child in self.sub_entries:
            yield from child.enhanced_toc_in_playback_order


@dataclass(frozen=True)
class Audiobook:
    manifest: Manifest

    @cached_property
    def segments_by_toc_id(self) -> dict[int, Sequence[AudioSegment]]:
        return {
            id(toc_segments.toc_entry): toc_segments.audio_segments
            for toc_segments in audio_segments_for_all_toc_entries(
                all_toc_entries=self.manifest.toc_in_playback_order,
                all_tracks=self.manifest.reading_order,
            )
        }

    @cached_property
    def enhanced_toc(self) -> Sequence[EnhancedToCEntry]:
        return self.generate_enhanced_toc(toc=self.manifest.effective_toc)

    def generate_enhanced_toc(
        self,
        toc: Sequence[ToCEntry] | None,
        depth: int = 0,
    ) -> Sequence[EnhancedToCEntry]:
        """Recursively generate enhanced ToC entries."""
        return (
            [
                EnhancedToCEntry(
                    depth=depth,
                    duration=sum(
                        segment.duration
                        for segment in self.segments_by_toc_id[id(entry)]
                    ),
                    actual_duration=sum(
                        segment.actual_duration
                        for segment in self.segments_by_toc_id[id(entry)]
                    ),
                    audio_segments=self.segments_by_toc_id[id(entry)],
                    sub_entries=self.generate_enhanced_toc(
                        toc=entry.children, depth=depth + 1
                    ),
                    **entry.model_dump(),
                )
                for entry in toc
            ]
            if toc is not None
            else []
        )

    @property
    def toc_in_playback_order(self) -> Generator[ToCEntry]:
        """Iterator yielding all ToC entries in the order that they appear in the manifest.

        If there is no `toc` object (or it is empty), we will construct
        the ToC using the manifest's `readingOrder`.
        """
        yield from self.manifest.toc_in_playback_order

    @property
    def enhanced_toc_in_playback_order(self) -> Generator[EnhancedToCEntry]:
        """Iterator yielding all ToC entries in the order that they appear in the manifest.

        If there is no `toc` object (or it is empty), we will construct
        the ToC using the manifest's `readingOrder`.
        """
        for entry in self.enhanced_toc:
            yield from entry.enhanced_toc_in_playback_order

    @cached_property
    def pre_toc_unplayed_audio_segments(self) -> Sequence[AudioSegment]:
        """Audio segments that precede the first ToC segment and, thus, are not played."""
        toc_from_first_track = ToCEntry.from_track(track=self.manifest.reading_order[0])
        first_effective_toc = self.manifest.effective_toc[0]
        if first_effective_toc.href == toc_from_first_track.href:
            return []

        return audio_segments_for_toc_entry(
            entry=toc_from_first_track,
            next_entry=first_effective_toc,
            tracks=self.manifest.reading_order,
        ).audio_segments

    @cached_property
    def toc_total_duration(self) -> int:
        """The duration (in seconds) of this ToCEntry and its children."""
        return sum(toc.duration for toc in self.enhanced_toc_in_playback_order)

    @cached_property
    def toc_actual_total_duration(self) -> float:
        """The duration (in seconds) of this ToCEntry and its children."""
        return sum(toc.actual_duration for toc in self.enhanced_toc_in_playback_order)

    @classmethod
    def from_manifest_file(cls, filepath: Path | str) -> Self:
        directory_path = Path(filepath).parent
        manifest = Manifest.parse_file(filepath)
        for track in manifest.reading_order:
            # Try to load the track
            track_file = directory_path / track.href
            if track_file.is_file():
                track.actual_duration = MP3(track_file).info.length

        return cls(manifest=manifest)
