from __future__ import annotations

from collections.abc import Generator, Iterable, Sequence
from dataclasses import dataclass, field

from palace_tools.models.api.rwpm_audiobook import AudioTrack, ToCEntry
from palace_tools.utils.iteration import sliding_window


@dataclass
class AudioSegment:
    track: AudioTrack
    start: int
    end: int

    end_actual: float = 0.0

    # Post-init
    duration: int = field(init=False)
    actual_duration: float = field(init=False)

    def __post_init__(self) -> None:
        self.duration = self.end - self.start
        self.actual_duration = self.end_actual - self.start


@dataclass(frozen=True)
class ToCTrackBoundaries:
    toc_entry: ToCEntry
    first_track_index: int
    first_track_start_offset: int
    last_track_index: int
    last_track_end_offset: int
    last_track_end_actual_offset: float


@dataclass(frozen=True)
class ToCAudioSegmentSequence:
    toc_entry: ToCEntry
    audio_segments: Sequence[AudioSegment]


def _toc_track_boundaries(
    entry: ToCEntry,
    next_entry: ToCEntry | None,
    all_tracks: Sequence[AudioTrack],
) -> ToCTrackBoundaries:
    """Return the start and end track numbers and offsets for the audio segments of the given ToC entry.

    :param entry: The current ToC entry.
    :param next_entry: The next ToC entry, or None if this is the last entry.
    :param all_tracks: The list of *all* tracks in the audiobook.
    :return: ToCTrackBoundaries containing the start / end track boundaries for the ToC Entry.
    """
    track_index_by_href: dict[str, int] = {t.href: i for i, t in enumerate(all_tracks)}

    if not next_entry:
        # This is the last ToC entry, so it will use all the rest of the tracks.
        end_track_index = len(all_tracks) - 1
        end_track_offset = all_tracks[end_track_index].duration
        end_track_actual_offset = all_tracks[end_track_index].actual_duration
    elif entry.track_href == next_entry.track_href or next_entry.track_offset != 0:
        # This entry either starts and ends on the same track or...
        # ... the next entry doesn't start at the very beginning of its first track.
        # Either way, this one ends on the same track on which the next one starts.
        end_track_index = track_index_by_href[next_entry.track_href]
        end_track_offset = next_entry.track_offset
        end_track_actual_offset = next_entry.track_offset
    else:
        # The next entry starts right at the beginning of a subsequent track.
        # So this entry ends at the end of the track before the starting track the next entry.
        end_track_index = track_index_by_href[next_entry.track_href] - 1
        end_track_offset = all_tracks[end_track_index].duration
        end_track_actual_offset = all_tracks[end_track_index].actual_duration

    return ToCTrackBoundaries(
        toc_entry=entry,
        first_track_index=track_index_by_href[entry.track_href],
        first_track_start_offset=entry.track_offset,
        last_track_index=end_track_index,
        last_track_end_offset=end_track_offset,
        last_track_end_actual_offset=end_track_actual_offset,
    )


def audio_segments_for_toc_entry(
    entry: ToCEntry,
    next_entry: ToCEntry | None,
    tracks: Sequence[AudioTrack],
) -> ToCAudioSegmentSequence:
    boundaries = _toc_track_boundaries(
        entry=entry, next_entry=next_entry, all_tracks=tracks
    )

    # We always include the first track.
    first_track = tracks[boundaries.first_track_index]
    first_segment = AudioSegment(
        track=first_track,
        start=boundaries.first_track_start_offset,
        end=(
            boundaries.last_track_end_offset
            if boundaries.first_track_index == boundaries.last_track_index
            else first_track.duration
        ),
        end_actual=(
            boundaries.last_track_end_actual_offset
            if boundaries.first_track_index == boundaries.last_track_index
            else first_track.actual_duration
        ),
    )

    # We populate a last track segment object only if the first and last
    # tracks are not the same.
    last_segment = (
        AudioSegment(
            track=tracks[boundaries.last_track_index],
            start=0,
            end=boundaries.last_track_end_offset,
            end_actual=boundaries.last_track_end_actual_offset,
        )
        if boundaries.first_track_index != boundaries.last_track_index
        else None
    )

    # Intermediate audio segments, when present, comprise full tracks.
    intermediate_tracks = tracks[
        boundaries.first_track_index + 1 : boundaries.last_track_index  # noqa: E203
    ]
    intermediate_tracks_segments = [
        AudioSegment(
            track=track, start=0, end=track.duration, end_actual=track.actual_duration
        )
        for track in intermediate_tracks
    ]
    sequence = list(
        filter(None, (first_segment, *intermediate_tracks_segments, last_segment))
    )
    return ToCAudioSegmentSequence(toc_entry=entry, audio_segments=sequence)


def audio_segments_for_all_toc_entries(
    all_toc_entries: Iterable[ToCEntry],
    all_tracks: Sequence[AudioTrack],
) -> Generator[ToCAudioSegmentSequence]:
    for entry, next_entry in sliding_window(all_toc_entries, 2, nulls=1):
        if entry is None:
            raise ValueError(
                "The ToC entry cannot be None. It should always be present."
            )
        yield audio_segments_for_toc_entry(
            entry=entry, next_entry=next_entry, tracks=all_tracks
        )
