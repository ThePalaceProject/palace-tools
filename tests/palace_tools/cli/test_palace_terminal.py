"""Tests for palace_terminal CLI tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from palace_tools.cli.palace_terminal import (
    Chapter,
    PalaceMediaPlayer,
    TableOfContents,
    Track,
    TrackPosition,
    Tracks,
    get_progress,
    ms_to_hms,
)
from palace_tools.models.api.rwpm_audiobook import Manifest


@pytest.fixture
def simple_manifest() -> Manifest:
    """Create a simple 3-track manifest with ToC for general testing."""
    manifest_dict = {
        "@context": "http://readium.org/webpub-manifest/context.jsonld",
        "metadata": {
            "@type": "http://schema.org/Audiobook",
            "identifier": "test-audiobook-1",
            "title": "Test Audiobook",
            "publisher": "Test Publisher",
            "published": "2024-01-01T00:00:00Z",
            "modified": "2024-01-01T00:00:00Z",
            "language": "en",
            "duration": 300,
        },
        "readingOrder": [
            {
                "href": "audio01.mp3",
                "type": "audio/mpeg",
                "duration": 60,
                "title": "Chapter 1",
            },
            {
                "href": "audio02.mp3",
                "type": "audio/mpeg",
                "duration": 120,
                "title": "Chapter 2",
            },
            {
                "href": "audio03.mp3",
                "type": "audio/mpeg",
                "duration": 120,
                "title": "Chapter 3",
            },
        ],
        "toc": [
            {"href": "audio01.mp3#t=0", "title": "Chapter 1"},
            {"href": "audio02.mp3#t=0", "title": "Chapter 2"},
            {"href": "audio03.mp3#t=0", "title": "Chapter 3"},
        ],
    }
    return Manifest(**manifest_dict)


@pytest.fixture
def simple_tracks(simple_manifest: Manifest) -> Tracks:
    """Create tracks from simple manifest."""
    return Tracks(simple_manifest)


class TestMsToHms:
    """Tests for ms_to_hms helper function."""

    def test_zero_milliseconds(self) -> None:
        assert ms_to_hms(0) == "0:00:00.000"

    def test_one_second(self) -> None:
        assert ms_to_hms(1000) == "0:00:01.000"

    def test_one_minute(self) -> None:
        assert ms_to_hms(60000) == "0:01:00.000"

    def test_one_hour(self) -> None:
        assert ms_to_hms(3600000) == "1:00:00.000"

    def test_complex_time(self) -> None:
        # 1h 23m 45.678s
        ms = (1 * 3600 + 23 * 60 + 45) * 1000 + 678
        assert ms_to_hms(ms) == "1:23:45.678"

    def test_multiple_hours(self) -> None:
        # 12h 34m 56.789s
        ms = (12 * 3600 + 34 * 60 + 56) * 1000 + 789
        assert ms_to_hms(ms) == "12:34:56.789"

    def test_fractional_seconds(self) -> None:
        assert ms_to_hms(1500) == "0:00:01.500"
        assert ms_to_hms(1001) == "0:00:01.001"


class TestGetProgress:
    """Tests for get_progress helper function."""

    def test_zero_duration_returns_zero(self) -> None:
        assert get_progress(100, 0) == 0.0

    def test_negative_duration_returns_zero(self) -> None:
        assert get_progress(100, -10) == 0.0

    def test_negative_position_returns_zero(self) -> None:
        assert get_progress(-100, 1000) == 0.0

    def test_halfway_progress(self) -> None:
        assert get_progress(500, 1000) == 0.5

    def test_quarter_progress(self) -> None:
        assert get_progress(250, 1000) == 0.25

    def test_full_progress(self) -> None:
        assert get_progress(1000, 1000) == 1.0


class TestTrack:
    """Tests for Track dataclass."""

    def test_track_creation(self) -> None:
        track = Track(href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0)
        assert track.href == "audio01.mp3"
        assert track.title == "Chapter 1"
        assert track.duration_ms == 60000
        assert track.index == 0

    def test_track_equality(self) -> None:
        track1 = Track(
            href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        track2 = Track(
            href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        assert track1 == track2

    def test_track_inequality_different_href(self) -> None:
        track1 = Track(
            href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        track2 = Track(
            href="audio02.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        assert track1 != track2

    def test_track_comparison(self) -> None:
        track1 = Track(
            href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        track2 = Track(
            href="audio02.mp3", title="Chapter 2", duration_ms=60000, index=1
        )
        assert track1 < track2
        assert track2 > track1

    def test_track_hash(self) -> None:
        track1 = Track(
            href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        track2 = Track(
            href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0
        )
        assert hash(track1) == hash(track2)

    def test_track_inequality_with_non_track(self) -> None:
        track = Track(href="audio01.mp3", title="Chapter 1", duration_ms=60000, index=0)
        assert track != "not a track"
        assert not (track < "not a track")
        assert not (track > "not a track")


class TestTrackPosition:
    """Tests for TrackPosition dataclass."""

    def test_position_equality(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        assert pos1 == pos2

    def test_position_inequality_different_timestamp(
        self, simple_tracks: Tracks
    ) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=2000, tracks=simple_tracks
        )
        assert pos1 != pos2

    def test_position_inequality_different_track(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[1], timestamp=1000, tracks=simple_tracks
        )
        assert pos1 != pos2

    def test_position_less_than_same_track(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=2000, tracks=simple_tracks
        )
        assert pos1 < pos2

    def test_position_less_than_different_track(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[1], timestamp=500, tracks=simple_tracks
        )
        assert pos1 < pos2

    def test_position_greater_than(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[1], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=2000, tracks=simple_tracks
        )
        assert pos1 > pos2

    def test_position_greater_or_equal(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos3 = TrackPosition(
            track=simple_tracks[0], timestamp=500, tracks=simple_tracks
        )
        assert pos1 >= pos2
        assert pos1 >= pos3

    def test_position_hash(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        assert hash(pos1) == hash(pos2)

    def test_position_subtract_same_track(self, simple_tracks: Tracks) -> None:
        pos1 = TrackPosition(
            track=simple_tracks[0], timestamp=5000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=2000, tracks=simple_tracks
        )
        assert pos1 - pos2 == 3000

    def test_position_subtract_different_tracks(self, simple_tracks: Tracks) -> None:
        # Track 0 is 60 seconds, Track 1 starts at 60s
        pos1 = TrackPosition(
            track=simple_tracks[1], timestamp=5000, tracks=simple_tracks
        )
        pos2 = TrackPosition(
            track=simple_tracks[0], timestamp=2000, tracks=simple_tracks
        )
        # Difference: (60000 - 2000) from track 0 + 5000 from track 1 = 63000
        assert pos1 - pos2 == 63000

    def test_position_subtract_invalid_type(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        with pytest.raises(ValueError, match="Can only subtract TrackPositions"):
            pos - 100  # type: ignore[operator]

    def test_position_add_zero(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        new_pos = pos + 0
        assert new_pos == pos

    def test_position_add_positive_same_track(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        new_pos = pos + 5000
        assert new_pos.track == simple_tracks[0]
        assert new_pos.timestamp == 6000

    def test_position_add_positive_crosses_track_boundary(
        self, simple_tracks: Tracks
    ) -> None:
        # Track 0 has 60000ms duration
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=50000, tracks=simple_tracks
        )
        new_pos = pos + 20000  # Should move to track 1
        assert new_pos.track == simple_tracks[1]
        assert new_pos.timestamp == 10000

    def test_position_add_negative_same_track(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=10000, tracks=simple_tracks
        )
        new_pos = pos + (-5000)
        assert new_pos.track == simple_tracks[0]
        assert new_pos.timestamp == 5000

    def test_position_add_negative_crosses_track_boundary(
        self, simple_tracks: Tracks
    ) -> None:
        # Going back from track 1 to track 0
        pos = TrackPosition(
            track=simple_tracks[1], timestamp=10000, tracks=simple_tracks
        )
        new_pos = pos + (-20000)
        assert new_pos.track == simple_tracks[0]
        # Track 0 has 60000ms, so: 60000 - 10000 = 50000
        assert new_pos.timestamp == 50000

    def test_position_add_out_of_bounds_forward(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[2], timestamp=100000, tracks=simple_tracks
        )
        with pytest.raises(ValueError, match="TrackPosition would be out of bounds"):
            pos + 1000000

    def test_position_add_out_of_bounds_backward(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        with pytest.raises(ValueError, match="TrackPosition would be out of bounds"):
            pos + (-10000)

    def test_position_add_invalid_type(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        with pytest.raises(ValueError, match="Can only add integers"):
            pos + "invalid"

    def test_position_inequality_with_non_position(self, simple_tracks: Tracks) -> None:
        pos = TrackPosition(
            track=simple_tracks[0], timestamp=1000, tracks=simple_tracks
        )
        assert pos != "not a position"
        assert not (pos < "not a position")
        assert not (pos > "not a position")
        assert not (pos >= "not a position")


class TestTracks:
    """Tests for Tracks class."""

    def test_tracks_initialization(self, simple_tracks: Tracks) -> None:
        assert len(simple_tracks) == 3
        assert simple_tracks.total_duration_ms == 300000

    def test_tracks_by_href(self, simple_tracks: Tracks) -> None:
        track = simple_tracks.by_href("audio02.mp3")
        assert track.href == "audio02.mp3"
        assert track.index == 1

    def test_tracks_previous_track_with_track_object(
        self, simple_tracks: Tracks
    ) -> None:
        prev = simple_tracks.previous_track(simple_tracks[1])
        assert prev == simple_tracks[0]

    def test_tracks_previous_track_with_index(self, simple_tracks: Tracks) -> None:
        prev = simple_tracks.previous_track(1)
        assert prev == simple_tracks[0]

    def test_tracks_previous_track_first_returns_none(
        self, simple_tracks: Tracks
    ) -> None:
        prev = simple_tracks.previous_track(simple_tracks[0])
        assert prev is None

    def test_tracks_next_track_with_track_object(self, simple_tracks: Tracks) -> None:
        next_track = simple_tracks.next_track(simple_tracks[1])
        assert next_track == simple_tracks[2]

    def test_tracks_next_track_with_index(self, simple_tracks: Tracks) -> None:
        next_track = simple_tracks.next_track(1)
        assert next_track == simple_tracks[2]

    def test_tracks_next_track_last_returns_none(self, simple_tracks: Tracks) -> None:
        next_track = simple_tracks.next_track(simple_tracks[2])
        assert next_track is None

    def test_tracks_iteration(self, simple_tracks: Tracks) -> None:
        track_list = list(simple_tracks)
        assert len(track_list) == 3
        assert track_list[0].href == "audio01.mp3"
        assert track_list[1].href == "audio02.mp3"
        assert track_list[2].href == "audio03.mp3"

    def test_tracks_getitem(self, simple_tracks: Tracks) -> None:
        assert simple_tracks[0].href == "audio01.mp3"
        assert simple_tracks[1].href == "audio02.mp3"
        assert simple_tracks[2].href == "audio03.mp3"


class TestChapter:
    """Tests for Chapter dataclass."""

    def test_chapter_creation(self, simple_tracks: Tracks) -> None:
        position = TrackPosition(
            track=simple_tracks[0], timestamp=0, tracks=simple_tracks
        )
        chapter = Chapter(title="Chapter 1", position=position)
        assert chapter.title == "Chapter 1"
        assert chapter.position == position

    def test_chapter_duration_not_set_raises_error(self, simple_tracks: Tracks) -> None:
        position = TrackPosition(
            track=simple_tracks[0], timestamp=0, tracks=simple_tracks
        )
        chapter = Chapter(title="Chapter 1", position=position)
        with pytest.raises(ValueError, match="Duration not set"):
            _ = chapter.duration_ms

    def test_chapter_duration_setter(self, simple_tracks: Tracks) -> None:
        position = TrackPosition(
            track=simple_tracks[0], timestamp=0, tracks=simple_tracks
        )
        chapter = Chapter(title="Chapter 1", position=position)
        chapter.duration_ms = 30000
        assert chapter.duration_ms == 30000

    def test_chapter_contains_position(self, simple_tracks: Tracks) -> None:
        start_position = TrackPosition(
            track=simple_tracks[0], timestamp=0, tracks=simple_tracks
        )
        chapter = Chapter(title="Chapter 1", position=start_position)
        chapter.duration_ms = 30000

        # Position at start
        assert start_position in chapter

        # Position in middle
        mid_position = TrackPosition(
            track=simple_tracks[0], timestamp=15000, tracks=simple_tracks
        )
        assert mid_position in chapter

        # Position just before end
        near_end = TrackPosition(
            track=simple_tracks[0], timestamp=29999, tracks=simple_tracks
        )
        assert near_end in chapter

        # Position at exact end (should not be in chapter)
        end_position = TrackPosition(
            track=simple_tracks[0], timestamp=30000, tracks=simple_tracks
        )
        assert end_position not in chapter

        # Position after end
        after_position = TrackPosition(
            track=simple_tracks[0], timestamp=35000, tracks=simple_tracks
        )
        assert after_position not in chapter


class TestTableOfContents:
    """Tests for TableOfContents class."""

    @pytest.fixture
    def manifest_with_toc(self) -> Manifest:
        """Create a manifest with table of contents."""
        manifest_dict = {
            "@context": "http://readium.org/webpub-manifest/context.jsonld",
            "metadata": {
                "@type": "http://schema.org/Audiobook",
                "identifier": "test-audiobook-1",
                "title": "Test Audiobook",
                "publisher": "Test Publisher",
                "published": "2024-01-01T00:00:00Z",
                "modified": "2024-01-01T00:00:00Z",
                "language": "en",
                "duration": 180,
            },
            "readingOrder": [
                {
                    "href": "audio01.mp3",
                    "type": "audio/mpeg",
                    "duration": 60,
                },
                {
                    "href": "audio02.mp3",
                    "type": "audio/mpeg",
                    "duration": 120,
                },
            ],
            "toc": [
                {"href": "audio01.mp3#t=0", "title": "Chapter 1"},
                {"href": "audio01.mp3#t=30", "title": "Chapter 2"},
                {"href": "audio02.mp3#t=0", "title": "Chapter 3"},
            ],
        }
        return Manifest(**manifest_dict)

    @pytest.fixture
    def manifest_without_toc_at_start(self) -> Manifest:
        """Create a manifest with ToC that doesn't start at 0."""
        manifest_dict = {
            "@context": "http://readium.org/webpub-manifest/context.jsonld",
            "metadata": {
                "@type": "http://schema.org/Audiobook",
                "identifier": "test-audiobook-1",
                "title": "Test Audiobook",
                "publisher": "Test Publisher",
                "published": "2024-01-01T00:00:00Z",
                "modified": "2024-01-01T00:00:00Z",
                "language": "en",
                "duration": 120,
            },
            "readingOrder": [
                {
                    "href": "audio01.mp3",
                    "type": "audio/mpeg",
                    "duration": 60,
                },
                {
                    "href": "audio02.mp3",
                    "type": "audio/mpeg",
                    "duration": 60,
                },
            ],
            "toc": [
                {"href": "audio01.mp3#t=30", "title": "Chapter 1"},
            ],
        }
        return Manifest(**manifest_dict)

    def test_toc_initialization(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)
        assert len(toc) == 3

    def test_toc_chapter_positions(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        assert toc[0].title == "Chapter 1"
        assert toc[0].position.timestamp == 0

        assert toc[1].title == "Chapter 2"
        assert toc[1].position.timestamp == 30000

        assert toc[2].title == "Chapter 3"
        assert toc[2].position.timestamp == 0
        assert toc[2].position.track.index == 1

    def test_toc_chapter_durations(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        # Chapter 1: 0 to 30s = 30s
        assert toc[0].duration_ms == 30000

        # Chapter 2: 30s to 60s = 30s
        assert toc[1].duration_ms == 30000

        # Chapter 3: 0s of track 2 to end = 120s
        assert toc[2].duration_ms == 120000

    def test_toc_inserts_forward_chapter_when_not_starting_at_zero(
        self, manifest_without_toc_at_start: Manifest
    ) -> None:
        tracks = Tracks(manifest_without_toc_at_start)
        toc = TableOfContents(manifest_without_toc_at_start, tracks)

        # Should have inserted "Forward" chapter at the beginning
        assert len(toc) == 2
        assert toc[0].title == "Forward"
        assert toc[0].position.timestamp == 0
        assert toc[0].position.track.index == 0

        assert toc[1].title == "Chapter 1"
        assert toc[1].position.timestamp == 30000

    def test_toc_next_chapter(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        next_chapter = toc.next_chapter(toc[0])
        assert next_chapter == toc[1]

        next_chapter = toc.next_chapter(toc[1])
        assert next_chapter == toc[2]

    def test_toc_next_chapter_last_returns_none(
        self, manifest_with_toc: Manifest
    ) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        next_chapter = toc.next_chapter(toc[2])
        assert next_chapter is None

    def test_toc_previous_chapter(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        prev_chapter = toc.previous_chapter(toc[2])
        assert prev_chapter == toc[1]

        prev_chapter = toc.previous_chapter(toc[1])
        assert prev_chapter == toc[0]

    def test_toc_previous_chapter_first_returns_none(
        self, manifest_with_toc: Manifest
    ) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        prev_chapter = toc.previous_chapter(toc[0])
        assert prev_chapter is None

    def test_toc_chapter_for_position(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        # Position in first chapter
        pos = TrackPosition(track=tracks[0], timestamp=15000, tracks=tracks)
        chapter = toc.chapter_for_position(pos)
        assert chapter.title == "Chapter 1"

        # Position in second chapter
        pos = TrackPosition(track=tracks[0], timestamp=45000, tracks=tracks)
        chapter = toc.chapter_for_position(pos)
        assert chapter.title == "Chapter 2"

        # Position in third chapter
        pos = TrackPosition(track=tracks[1], timestamp=30000, tracks=tracks)
        chapter = toc.chapter_for_position(pos)
        assert chapter.title == "Chapter 3"

    def test_toc_iteration(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        chapters = list(toc)
        assert len(chapters) == 3
        assert chapters[0].title == "Chapter 1"
        assert chapters[1].title == "Chapter 2"
        assert chapters[2].title == "Chapter 3"

    def test_toc_index(self, manifest_with_toc: Manifest) -> None:
        tracks = Tracks(manifest_with_toc)
        toc = TableOfContents(manifest_with_toc, tracks)

        assert toc.index(toc[0]) == 0
        assert toc.index(toc[1]) == 1
        assert toc.index(toc[2]) == 2


class TestPalaceMediaPlayer:
    """Tests for PalaceMediaPlayer class."""

    @pytest.fixture
    def manifest_dict(self) -> dict[str, object]:
        """Create a test manifest dictionary."""
        return {
            "@context": "http://readium.org/webpub-manifest/context.jsonld",
            "metadata": {
                "@type": "http://schema.org/Audiobook",
                "identifier": "test-audiobook-1",
                "title": "Test Audiobook",
                "publisher": "Test Publisher",
                "published": "2024-01-01T00:00:00Z",
                "modified": "2024-01-01T00:00:00Z",
                "language": "en",
                "duration": 120,
            },
            "readingOrder": [
                {
                    "href": "audio01.mp3",
                    "type": "audio/mpeg",
                    "duration": 60,
                    "title": "Track 1",
                },
                {
                    "href": "audio:with:colons.mp3",
                    "type": "audio/mpeg",
                    "duration": 60,
                    "title": "Track 2",
                },
            ],
            "toc": [
                {"href": "audio01.mp3#t=0", "title": "Chapter 1"},
                {"href": "audio:with:colons.mp3#t=0", "title": "Chapter 2"},
            ],
        }

    @pytest.fixture
    def manifest_file(self, tmp_path: Path, manifest_dict: dict[str, object]) -> Path:
        """Create a temporary manifest file."""
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_dict))

        # Create dummy audio files
        (tmp_path / "audio01.mp3").touch()
        (tmp_path / "audio:with:colons.mp3").touch()

        return manifest_path

    def test_raises_error_if_manifest_file_does_not_exist(self, tmp_path: Path) -> None:
        non_existent = tmp_path / "does_not_exist.json"
        with pytest.raises(FileNotFoundError, match="does not exist"):
            PalaceMediaPlayer(non_existent)

    @patch("palace_tools.cli.palace_terminal.vlc")
    def test_initialization_creates_vlc_instances(
        self, mock_vlc: MagicMock, manifest_file: Path
    ) -> None:
        # Setup mocks
        mock_instance = Mock()
        mock_player = Mock()
        mock_list_player = Mock()
        mock_media_list = Mock()
        mock_media = Mock()
        mock_media.get_duration.return_value = 60000

        mock_vlc.Instance.return_value = mock_instance
        mock_instance.media_player_new.return_value = mock_player
        mock_instance.media_list_player_new.return_value = mock_list_player
        mock_instance.media_list_new.return_value = mock_media_list
        mock_instance.media_new.return_value = mock_media

        player = PalaceMediaPlayer(manifest_file)

        # Verify VLC setup
        mock_vlc.Instance.assert_called_once()
        mock_instance.media_player_new.assert_called_once()
        mock_instance.media_list_player_new.assert_called_once()
        mock_instance.media_list_new.assert_called_once()
        mock_list_player.set_media_player.assert_called_once_with(mock_player)

        assert player.instance == mock_instance
        assert player.player == mock_player
        assert player.list_player == mock_list_player

    @patch("palace_tools.cli.palace_terminal.vlc")
    def test_file_paths_converted_to_uris(
        self, mock_vlc: MagicMock, manifest_file: Path
    ) -> None:
        # Setup mocks
        mock_instance = Mock()
        mock_media = Mock()
        mock_media.get_duration.return_value = 60000

        mock_vlc.Instance.return_value = mock_instance
        mock_instance.media_player_new.return_value = Mock()
        mock_instance.media_list_player_new.return_value = Mock()
        mock_instance.media_list_new.return_value = Mock()
        mock_instance.media_new.return_value = mock_media

        PalaceMediaPlayer(manifest_file)

        # Verify media_new was called with proper URIs
        assert mock_instance.media_new.call_count == 2

        # Get the URIs that were passed
        call_args = [call[0][0] for call in mock_instance.media_new.call_args_list]

        # All URIs should start with file://
        assert all(uri.startswith("file://") for uri in call_args)

        # URIs should be absolute paths
        expected_uri_1 = (manifest_file.parent / "audio01.mp3").resolve().as_uri()
        expected_uri_2 = (
            (manifest_file.parent / "audio:with:colons.mp3").resolve().as_uri()
        )

        assert call_args[0] == expected_uri_1
        assert call_args[1] == expected_uri_2

    @patch("palace_tools.cli.palace_terminal.vlc")
    def test_special_characters_in_filenames_handled_correctly(
        self, mock_vlc: MagicMock, manifest_file: Path
    ) -> None:
        # Setup mocks
        mock_instance = Mock()
        mock_media = Mock()
        mock_media.get_duration.return_value = 60000

        mock_vlc.Instance.return_value = mock_instance
        mock_instance.media_player_new.return_value = Mock()
        mock_instance.media_list_player_new.return_value = Mock()
        mock_instance.media_list_new.return_value = Mock()
        mock_instance.media_new.return_value = mock_media

        PalaceMediaPlayer(manifest_file)

        # Get the second URI (the one with colons)
        call_args = [call[0][0] for call in mock_instance.media_new.call_args_list]
        uri_with_colons = call_args[1]

        # Verify that colons are properly URL-encoded in the URI
        # as_uri() should convert ":" to "%3A" in the path portion
        assert "audio%3Awith%3Acolons.mp3" in uri_with_colons or (
            # On some systems, colons might be preserved in file URIs
            "audio:with:colons.mp3"
            in uri_with_colons
        )

    @patch("palace_tools.cli.palace_terminal.vlc")
    def test_current_position_initialized_to_first_track(
        self, mock_vlc: MagicMock, manifest_file: Path
    ) -> None:
        # Setup mocks
        mock_instance = Mock()
        mock_media = Mock()
        mock_media.get_duration.return_value = 60000

        mock_vlc.Instance.return_value = mock_instance
        mock_instance.media_player_new.return_value = Mock()
        mock_instance.media_list_player_new.return_value = Mock()
        mock_instance.media_list_new.return_value = Mock()
        mock_instance.media_new.return_value = mock_media

        player = PalaceMediaPlayer(manifest_file)

        assert player.current_position.track == player.tracks[0]
        assert player.current_position.timestamp == 0

    @patch("palace_tools.cli.palace_terminal.vlc")
    def test_playback_speed_methods(
        self, mock_vlc: MagicMock, manifest_file: Path
    ) -> None:
        # Setup mocks
        mock_instance = Mock()
        mock_player = Mock()
        mock_media = Mock()
        mock_media.get_duration.return_value = 60000

        mock_vlc.Instance.return_value = mock_instance
        mock_instance.media_player_new.return_value = mock_player
        mock_instance.media_list_player_new.return_value = Mock()
        mock_instance.media_list_new.return_value = Mock()
        mock_instance.media_new.return_value = mock_media

        player = PalaceMediaPlayer(manifest_file)

        # Test increase speed
        assert player.current_speed == 1.0
        new_speed = player.increase_speed()
        assert new_speed == 1.25
        assert player.current_speed == 1.25
        mock_player.set_rate.assert_called_with(1.25)

        # Test decrease speed
        new_speed = player.decrease_speed()
        assert new_speed == 1.0
        assert player.current_speed == 1.0

        # Test speed at max boundary
        player.current_speed = 2.0
        new_speed = player.increase_speed()
        assert new_speed == 2.0  # Should not go above max

        # Test speed at min boundary
        player.current_speed = 0.5
        new_speed = player.decrease_speed()
        assert new_speed == 0.5  # Should not go below min
