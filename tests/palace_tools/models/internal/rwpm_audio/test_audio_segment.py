"""Tests for audio_segment module."""

from collections.abc import Generator

import pytest

from palace_tools.models.api.rwpm_audiobook import AudioTrack, ToCEntry
from palace_tools.models.internal.rwpm_audio.audio_segment import (
    AudioSegment,
    ToCAudioSegmentSequence,
    _toc_track_boundaries,
    audio_segments_for_all_toc_entries,
    audio_segments_for_toc_entry,
)


class AudioSegmentFixture:
    """Fixture providing helper methods for audio segment tests."""

    def create_track(
        self,
        href: str = "track1.mp3",
        title: str = "Track 1",
        duration: int = 100,
        actual_duration: float = 99.5,
    ) -> AudioTrack:
        """Create an AudioTrack for testing."""
        return AudioTrack(
            href=href,
            title=title,
            type="audio/mpeg",
            duration=duration,
            actual_duration=actual_duration,
        )

    def create_toc_entry(
        self,
        href: str = "track1.mp3#t=0",
        title: str = "Chapter 1",
    ) -> ToCEntry:
        """Create a ToCEntry for testing."""
        return ToCEntry(href=href, title=title)


@pytest.fixture()
def audio_segment_fixture() -> AudioSegmentFixture:
    """Fixture providing helper methods for audio segment tests."""
    return AudioSegmentFixture()


class TestAudioSegment:
    """Tests for AudioSegment dataclass."""

    def test_audio_segment_initialization(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """AudioSegment should initialize with correct values."""
        track = audio_segment_fixture.create_track(duration=100, actual_duration=99.5)
        segment = AudioSegment(track=track, start=10, end=50, end_actual=49.5)

        assert segment.track == track
        assert segment.start == 10
        assert segment.end == 50
        assert segment.end_actual == 49.5

    def test_audio_segment_duration_calculation(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """AudioSegment should calculate duration correctly in __post_init__."""
        track = audio_segment_fixture.create_track()
        segment = AudioSegment(track=track, start=10, end=50, end_actual=49.5)

        assert segment.duration == 40  # 50 - 10
        assert segment.actual_duration == 39.5  # 49.5 - 10

    def test_audio_segment_full_track(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """AudioSegment for full track should have duration equal to track duration."""
        track = audio_segment_fixture.create_track(duration=100, actual_duration=99.5)
        segment = AudioSegment(
            track=track, start=0, end=100, end_actual=track.actual_duration
        )

        assert segment.duration == 100
        assert segment.actual_duration == 99.5

    def test_audio_segment_zero_duration(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """AudioSegment with same start and end should have zero duration."""
        track = audio_segment_fixture.create_track()
        segment = AudioSegment(track=track, start=50, end=50, end_actual=50.0)

        assert segment.duration == 0
        assert segment.actual_duration == 0.0


class TestTocTrackBoundaries:
    """Tests for _toc_track_boundaries function."""

    def test_single_track_partial_segment(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Single track with partial segment should calculate boundaries correctly."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track1, track2]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=10", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track1.mp3#t=50", "Chapter 2")

        boundaries = _toc_track_boundaries(
            entry=toc1, next_entry=toc2, all_tracks=tracks
        )

        assert boundaries.first_track_index == 0
        assert boundaries.first_track_start_offset == 10
        assert boundaries.last_track_index == 0
        assert boundaries.last_track_end_offset == 50

    def test_multi_track_segment(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Multi-track segment should span across tracks."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=100, actual_duration=99.5
        )
        track3 = audio_segment_fixture.create_track(
            "track3.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track1, track2, track3]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=50", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track3.mp3#t=25", "Chapter 2")

        boundaries = _toc_track_boundaries(
            entry=toc1, next_entry=toc2, all_tracks=tracks
        )

        assert boundaries.first_track_index == 0
        assert boundaries.first_track_start_offset == 50
        assert boundaries.last_track_index == 2
        assert boundaries.last_track_end_offset == 25

    def test_last_entry_uses_all_remaining_tracks(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Last ToC entry should extend to end of last track."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=200, actual_duration=199.5
        )
        tracks = [track1, track2]

        toc1 = audio_segment_fixture.create_toc_entry("track2.mp3#t=10", "Chapter 1")

        boundaries = _toc_track_boundaries(
            entry=toc1, next_entry=None, all_tracks=tracks
        )

        assert boundaries.first_track_index == 1
        assert boundaries.first_track_start_offset == 10
        assert boundaries.last_track_index == 1
        assert boundaries.last_track_end_offset == 200
        assert boundaries.last_track_end_actual_offset == 199.5

    def test_next_entry_at_track_start_ends_previous_track(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """When next entry starts at beginning of track, current entry ends at previous track."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=100, actual_duration=99.5
        )
        track3 = audio_segment_fixture.create_track(
            "track3.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track1, track2, track3]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track3.mp3#t=0", "Chapter 2")

        boundaries = _toc_track_boundaries(
            entry=toc1, next_entry=toc2, all_tracks=tracks
        )

        assert boundaries.first_track_index == 0
        assert boundaries.last_track_index == 1  # Ends at track2, not track3
        assert boundaries.last_track_end_offset == 100
        assert boundaries.last_track_end_actual_offset == 99.5


class TestAudioSegmentsForTocEntry:
    """Tests for audio_segments_for_toc_entry function."""

    def test_single_track_full_segment(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Single track with full content should create one segment."""
        track = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")

        result = audio_segments_for_toc_entry(
            entry=toc1, next_entry=None, tracks=tracks
        )

        assert result.toc_entry == toc1
        assert len(result.audio_segments) == 1
        assert result.audio_segments[0].track == track
        assert result.audio_segments[0].start == 0
        assert result.audio_segments[0].end == 100
        assert result.audio_segments[0].duration == 100

    def test_single_track_partial_segment(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Single track with partial content should create one segment with correct bounds."""
        track = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=10", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track1.mp3#t=50", "Chapter 2")

        result = audio_segments_for_toc_entry(
            entry=toc1, next_entry=toc2, tracks=tracks
        )

        assert len(result.audio_segments) == 1
        assert result.audio_segments[0].start == 10
        assert result.audio_segments[0].end == 50
        assert result.audio_segments[0].duration == 40

    def test_multi_track_segment_with_intermediate_tracks(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Multi-track segment should include first, intermediate, and last segments."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=150, actual_duration=149.5
        )
        track3 = audio_segment_fixture.create_track(
            "track3.mp3", duration=120, actual_duration=119.5
        )
        tracks = [track1, track2, track3]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=50", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track3.mp3#t=60", "Chapter 2")

        result = audio_segments_for_toc_entry(
            entry=toc1, next_entry=toc2, tracks=tracks
        )

        assert len(result.audio_segments) == 3

        # First segment: partial track1 (50-100)
        assert result.audio_segments[0].track == track1
        assert result.audio_segments[0].start == 50
        assert result.audio_segments[0].end == 100
        assert result.audio_segments[0].duration == 50

        # Intermediate segment: full track2
        assert result.audio_segments[1].track == track2
        assert result.audio_segments[1].start == 0
        assert result.audio_segments[1].end == 150
        assert result.audio_segments[1].duration == 150

        # Last segment: partial track3 (0-60)
        assert result.audio_segments[2].track == track3
        assert result.audio_segments[2].start == 0
        assert result.audio_segments[2].end == 60
        assert result.audio_segments[2].duration == 60

    def test_two_adjacent_tracks_no_intermediate(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Two adjacent tracks should create two segments without intermediate."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track1, track2]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=50", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track2.mp3#t=60", "Chapter 2")

        result = audio_segments_for_toc_entry(
            entry=toc1, next_entry=toc2, tracks=tracks
        )

        assert len(result.audio_segments) == 2

        # First segment
        assert result.audio_segments[0].track == track1
        assert result.audio_segments[0].start == 50
        assert result.audio_segments[0].end == 100

        # Last segment
        assert result.audio_segments[1].track == track2
        assert result.audio_segments[1].start == 0
        assert result.audio_segments[1].end == 60


class TestAudioSegmentsForAllTocEntries:
    """Tests for audio_segments_for_all_toc_entries function."""

    def test_multiple_toc_entries(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """Multiple ToC entries should generate correct segments for each."""
        track1 = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audio_segment_fixture.create_track(
            "track2.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track1, track2]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")
        toc2 = audio_segment_fixture.create_toc_entry("track1.mp3#t=50", "Chapter 2")
        toc3 = audio_segment_fixture.create_toc_entry("track2.mp3#t=20", "Chapter 3")
        toc_entries = [toc1, toc2, toc3]

        results = list(
            audio_segments_for_all_toc_entries(
                all_toc_entries=toc_entries, all_tracks=tracks
            )
        )

        assert len(results) == 3
        assert all(isinstance(r, ToCAudioSegmentSequence) for r in results)
        assert results[0].toc_entry == toc1
        assert results[1].toc_entry == toc2
        assert results[2].toc_entry == toc3

    def test_single_toc_entry(self, audio_segment_fixture: AudioSegmentFixture) -> None:
        """Single ToC entry should generate one segment sequence."""
        track = audio_segment_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        tracks = [track]

        toc1 = audio_segment_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")

        results = list(
            audio_segments_for_all_toc_entries(
                all_toc_entries=[toc1], all_tracks=tracks
            )
        )

        assert len(results) == 1
        assert results[0].toc_entry == toc1

    def test_none_entry_raises_value_error(
        self, audio_segment_fixture: AudioSegmentFixture
    ) -> None:
        """None entry should raise ValueError."""
        # This tests the internal error handling in sliding_window usage
        # In normal usage, None entries shouldn't occur, but the function guards against it
        track = audio_segment_fixture.create_track()

        # We can't easily create a None entry in the sliding window in normal usage,
        # so this test documents the expected behavior if it somehow occurs
        # The function will raise ValueError if entry is None
        with pytest.raises(ValueError, match="ToC entry cannot be None"):
            # Create a generator that yields None
            def none_generator() -> Generator[None, None, None]:
                yield None

            list(
                audio_segments_for_all_toc_entries(
                    all_toc_entries=none_generator(),  # type: ignore[arg-type]
                    all_tracks=[track],
                )
            )
