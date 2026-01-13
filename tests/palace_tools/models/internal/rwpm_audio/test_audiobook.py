"""Tests for audiobook module."""

import datetime
from collections.abc import Sequence
from typing import Any

import pytest

from palace_tools.models.api.rwpm_audiobook import (
    AudioTrack,
    Manifest,
    ManifestMetadata,
    ToCEntry,
)
from palace_tools.models.internal.rwpm_audio.audio_segment import AudioSegment
from palace_tools.models.internal.rwpm_audio.audiobook import (
    Audiobook,
    EnhancedToCEntry,
)
from tests.fixtures.file import FixtureFile


class AudiobookFixture:
    """Fixture providing helper methods for audiobook tests."""

    def create_metadata(
        self,
        identifier: str = "urn:isbn:1234567890",
        title: str = "Test Audiobook",
        duration: int = 1000,
    ) -> ManifestMetadata:
        """Create ManifestMetadata for testing."""
        return ManifestMetadata(
            **{
                "@type": "http://schema.org/Audiobook",
                "identifier": identifier,
                "title": title,
                "author": "Test Author",
                "publisher": "Test Publisher",
                "published": datetime.datetime(2024, 1, 1),
                "language": "en",
                "modified": datetime.datetime(2024, 1, 2),
                "duration": duration,
            }
        )

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
        children: Sequence[ToCEntry] | None = None,
    ) -> ToCEntry:
        """Create a ToCEntry for testing."""
        return ToCEntry(href=href, title=title, children=children)

    def create_manifest(
        self,
        tracks: list[AudioTrack] | None = None,
        toc: list[ToCEntry] | None = None,
        metadata: ManifestMetadata | None = None,
    ) -> Manifest:
        """Create a Manifest for testing."""
        if tracks is None:
            tracks = [self.create_track()]
        if metadata is None:
            metadata = self.create_metadata(duration=sum(t.duration for t in tracks))

        manifest_dict: dict[str, Any] = {
            "@context": "https://readium.org/webpub-manifest/context.jsonld",
            "metadata": metadata.model_dump(by_alias=True),
            "readingOrder": [t.model_dump(by_alias=True) for t in tracks],
        }

        if toc is not None:
            manifest_dict["toc"] = [t.model_dump(by_alias=True) for t in toc]

        return Manifest(**manifest_dict)


@pytest.fixture()
def audiobook_fixture() -> AudiobookFixture:
    """Fixture providing helper methods for audiobook tests."""
    return AudiobookFixture()


class TestEnhancedToCEntry:
    """Tests for EnhancedToCEntry class."""

    def test_enhanced_toc_entry_creation(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """EnhancedToCEntry should be created with additional fields."""
        segment = AudioSegment(
            track=audiobook_fixture.create_track(),
            start=0,
            end=100,
            end_actual=99.5,
        )

        entry = EnhancedToCEntry(
            href="track1.mp3#t=0",
            title="Chapter 1",
            depth=0,
            duration=100,
            audio_segments=[segment],
            sub_entries=[],
        )

        assert entry.href == "track1.mp3#t=0"
        assert entry.title == "Chapter 1"
        assert entry.depth == 0
        assert entry.duration == 100
        assert entry.audio_segments == [segment]
        assert entry.sub_entries == []

    def test_enhanced_toc_entry_with_children(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """EnhancedToCEntry should support nested sub_entries."""
        segment1 = AudioSegment(
            track=audiobook_fixture.create_track("track1.mp3"),
            start=0,
            end=50,
            end_actual=49.5,
        )
        segment2 = AudioSegment(
            track=audiobook_fixture.create_track("track1.mp3"),
            start=50,
            end=100,
            end_actual=99.5,
        )

        child1 = EnhancedToCEntry(
            href="track1.mp3#t=50",
            title="Section 1.1",
            depth=1,
            duration=50,
            audio_segments=[segment2],
            sub_entries=[],
        )

        parent = EnhancedToCEntry(
            href="track1.mp3#t=0",
            title="Chapter 1",
            depth=0,
            duration=100,
            audio_segments=[segment1],
            sub_entries=[child1],
        )

        assert len(parent.sub_entries) == 1
        assert parent.sub_entries[0] == child1
        assert parent.sub_entries[0].depth == 1

    def test_total_duration_single_entry(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """total_duration should equal duration for single entry."""
        segment = AudioSegment(
            track=audiobook_fixture.create_track(),
            start=0,
            end=100,
            end_actual=99.5,
        )

        entry = EnhancedToCEntry(
            href="track1.mp3#t=0",
            title="Chapter 1",
            depth=0,
            duration=100,
            audio_segments=[segment],
            sub_entries=[],
        )

        assert entry.total_duration == 100

    def test_total_duration_with_children(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """total_duration should include children durations."""
        segment1 = AudioSegment(
            track=audiobook_fixture.create_track(),
            start=0,
            end=50,
            end_actual=49.5,
        )
        segment2 = AudioSegment(
            track=audiobook_fixture.create_track(),
            start=50,
            end=100,
            end_actual=99.5,
        )

        child1 = EnhancedToCEntry(
            href="track1.mp3#t=50",
            title="Section 1.1",
            depth=1,
            duration=50,
            audio_segments=[segment2],
            sub_entries=[],
        )

        parent = EnhancedToCEntry(
            href="track1.mp3#t=0",
            title="Chapter 1",
            depth=0,
            duration=50,
            audio_segments=[segment1],
            sub_entries=[child1],
        )

        # Total should be parent (50) + child (50) = 100
        assert parent.total_duration == 100

    def test_enhanced_toc_in_playback_order_single_entry(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """enhanced_toc_in_playback_order should yield single entry."""
        segment = AudioSegment(
            track=audiobook_fixture.create_track(),
            start=0,
            end=100,
            end_actual=99.5,
        )

        entry = EnhancedToCEntry(
            href="track1.mp3#t=0",
            title="Chapter 1",
            depth=0,
            duration=100,
            audio_segments=[segment],
            sub_entries=[],
        )

        entries = list(entry.enhanced_toc_in_playback_order)
        assert len(entries) == 1
        assert entries[0] == entry

    def test_enhanced_toc_in_playback_order_with_children(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """enhanced_toc_in_playback_order should yield parent then children."""
        segment = AudioSegment(
            track=audiobook_fixture.create_track(),
            start=0,
            end=100,
            end_actual=99.5,
        )

        child1 = EnhancedToCEntry(
            href="track1.mp3#t=50",
            title="Section 1.1",
            depth=1,
            duration=50,
            audio_segments=[segment],
            sub_entries=[],
        )

        child2 = EnhancedToCEntry(
            href="track1.mp3#t=70",
            title="Section 1.2",
            depth=1,
            duration=30,
            audio_segments=[segment],
            sub_entries=[],
        )

        parent = EnhancedToCEntry(
            href="track1.mp3#t=0",
            title="Chapter 1",
            depth=0,
            duration=100,
            audio_segments=[segment],
            sub_entries=[child1, child2],
        )

        entries = list(parent.enhanced_toc_in_playback_order)
        assert len(entries) == 3
        assert entries[0] == parent
        assert entries[1] == child1
        assert entries[2] == child2


class TestAudiobook:
    """Tests for Audiobook class."""

    def test_audiobook_creation(self, audiobook_fixture: AudiobookFixture) -> None:
        """Audiobook should be created from a manifest."""
        manifest = audiobook_fixture.create_manifest()
        audiobook = Audiobook(manifest=manifest)

        assert audiobook.manifest == manifest

    def test_segments_by_toc_id_single_track(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """segments_by_toc_id should map ToC entries to their audio segments."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        segments_by_id = audiobook.segments_by_toc_id
        assert len(segments_by_id) == 1

        # Get the actual ToC entry from manifest (not the one we created)
        actual_toc = list(manifest.toc_in_playback_order)[0]
        toc_id = id(actual_toc)
        assert toc_id in segments_by_id
        assert len(segments_by_id[toc_id]) == 1
        assert segments_by_id[toc_id][0].track.href == "track1.mp3"

    def test_segments_by_toc_id_multiple_entries(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """segments_by_toc_id should handle multiple ToC entries."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        track2 = audiobook_fixture.create_track("track2.mp3", duration=100)

        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")
        toc2 = audiobook_fixture.create_toc_entry("track2.mp3#t=0", "Chapter 2")

        manifest = audiobook_fixture.create_manifest(
            tracks=[track1, track2], toc=[toc1, toc2]
        )
        audiobook = Audiobook(manifest=manifest)

        segments_by_id = audiobook.segments_by_toc_id
        assert len(segments_by_id) == 2

    def test_enhanced_toc_generation(self, audiobook_fixture: AudiobookFixture) -> None:
        """enhanced_toc should generate EnhancedToCEntry objects."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        enhanced_toc = audiobook.enhanced_toc
        assert len(enhanced_toc) == 1
        assert isinstance(enhanced_toc[0], EnhancedToCEntry)
        assert enhanced_toc[0].title == "Chapter 1"
        assert enhanced_toc[0].depth == 0
        assert enhanced_toc[0].duration == 100

    def test_enhanced_toc_with_nested_structure(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """enhanced_toc should preserve nested ToC structure."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)

        child1 = audiobook_fixture.create_toc_entry("track1.mp3#t=50", "Section 1.1")
        toc1 = audiobook_fixture.create_toc_entry(
            "track1.mp3#t=0", "Chapter 1", children=[child1]
        )

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        enhanced_toc = audiobook.enhanced_toc
        assert len(enhanced_toc) == 1
        assert enhanced_toc[0].depth == 0
        assert len(enhanced_toc[0].sub_entries) == 1
        assert enhanced_toc[0].sub_entries[0].depth == 1
        assert enhanced_toc[0].sub_entries[0].title == "Section 1.1"

    def test_enhanced_toc_in_playback_order(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """enhanced_toc_in_playback_order should yield all entries in order."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        track2 = audiobook_fixture.create_track("track2.mp3", duration=100)

        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")
        toc2 = audiobook_fixture.create_toc_entry("track2.mp3#t=0", "Chapter 2")

        manifest = audiobook_fixture.create_manifest(
            tracks=[track1, track2], toc=[toc1, toc2]
        )
        audiobook = Audiobook(manifest=manifest)

        entries = list(audiobook.enhanced_toc_in_playback_order)
        assert len(entries) == 2
        assert entries[0].title == "Chapter 1"
        assert entries[1].title == "Chapter 2"

    def test_enhanced_toc_in_playback_order_with_nesting(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """enhanced_toc_in_playback_order should yield nested entries in order."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)

        child1 = audiobook_fixture.create_toc_entry("track1.mp3#t=50", "Section 1.1")
        child2 = audiobook_fixture.create_toc_entry("track1.mp3#t=75", "Section 1.2")
        toc1 = audiobook_fixture.create_toc_entry(
            "track1.mp3#t=0", "Chapter 1", children=[child1, child2]
        )

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        entries = list(audiobook.enhanced_toc_in_playback_order)
        assert len(entries) == 3
        assert entries[0].title == "Chapter 1"
        assert entries[1].title == "Section 1.1"
        assert entries[2].title == "Section 1.2"

    def test_toc_total_duration(self, audiobook_fixture: AudiobookFixture) -> None:
        """toc_total_duration should sum all ToC entry durations."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        track2 = audiobook_fixture.create_track("track2.mp3", duration=150)

        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")
        toc2 = audiobook_fixture.create_toc_entry("track2.mp3#t=0", "Chapter 2")

        manifest = audiobook_fixture.create_manifest(
            tracks=[track1, track2], toc=[toc1, toc2]
        )
        audiobook = Audiobook(manifest=manifest)

        assert audiobook.toc_total_duration == 250

    def test_toc_actual_total_duration(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """toc_actual_total_duration should sum actual durations."""
        track1 = audiobook_fixture.create_track(
            "track1.mp3", duration=100, actual_duration=99.5
        )
        track2 = audiobook_fixture.create_track(
            "track2.mp3", duration=150, actual_duration=149.3
        )

        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")
        toc2 = audiobook_fixture.create_toc_entry("track2.mp3#t=0", "Chapter 2")

        manifest = audiobook_fixture.create_manifest(
            tracks=[track1, track2], toc=[toc1, toc2]
        )
        audiobook = Audiobook(manifest=manifest)

        assert audiobook.toc_actual_total_duration == pytest.approx(248.8, rel=0.01)

    def test_audiobook_without_explicit_toc(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """Audiobook without explicit ToC should generate ToC from reading order."""
        track1 = audiobook_fixture.create_track(
            "track1.mp3", title="Track 1", duration=100
        )
        track2 = audiobook_fixture.create_track(
            "track2.mp3", title="Track 2", duration=150
        )

        manifest = audiobook_fixture.create_manifest(tracks=[track1, track2], toc=None)
        audiobook = Audiobook(manifest=manifest)

        # Should generate ToC from tracks
        enhanced_toc = audiobook.enhanced_toc
        assert len(enhanced_toc) == 2
        assert enhanced_toc[0].title == "Track 1"
        assert enhanced_toc[1].title == "Track 2"

    def test_pre_toc_unplayed_audio_segments_no_gap(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """pre_toc_unplayed_audio_segments should be empty when ToC starts at beginning."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        assert len(audiobook.pre_toc_unplayed_audio_segments) == 0

    def test_pre_toc_unplayed_audio_segments_with_gap(
        self, audiobook_fixture: AudiobookFixture
    ) -> None:
        """pre_toc_unplayed_audio_segments should capture intro before first chapter."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=20", "Chapter 1")

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        segments = audiobook.pre_toc_unplayed_audio_segments
        assert len(segments) == 1
        assert segments[0].start == 0
        assert segments[0].end == 20
        assert segments[0].duration == 20

    def test_toc_in_playback_order(self, audiobook_fixture: AudiobookFixture) -> None:
        """toc_in_playback_order should delegate to manifest."""
        track1 = audiobook_fixture.create_track("track1.mp3", duration=100)
        toc1 = audiobook_fixture.create_toc_entry("track1.mp3#t=0", "Chapter 1")

        manifest = audiobook_fixture.create_manifest(tracks=[track1], toc=[toc1])
        audiobook = Audiobook(manifest=manifest)

        entries = list(audiobook.toc_in_playback_order)
        assert len(entries) == 1
        assert entries[0].title == "Chapter 1"

    def test_from_manifest_file(self, file_fixture: FixtureFile) -> None:
        """from_manifest_file should load an audiobook from a manifest file."""
        manifest_path = file_fixture("manifest.json")
        audiobook = Audiobook.from_manifest_file(manifest_path)

        # Verify the audiobook was created with the correct manifest
        assert audiobook.manifest.metadata.title == "Dungeon Crawler Carl"
        assert audiobook.manifest.metadata.identifier == "urn:isbn:9798350430943"
        assert audiobook.manifest.metadata.duration == 48702

        # Verify reading order was loaded
        assert len(audiobook.manifest.reading_order) == 50

        # Verify ToC was loaded
        toc_entries = list(audiobook.toc_in_playback_order)
        assert len(toc_entries) == 52
        assert toc_entries[0].title == "Opening Credits"
        assert toc_entries[1].title == "Chapter 1"

        # Verify enhanced ToC is generated
        enhanced_toc = audiobook.enhanced_toc
        assert len(enhanced_toc) == 52
        assert enhanced_toc[0].title == "Opening Credits"
        assert enhanced_toc[0].depth == 0

    def test_from_manifest_file_with_str_path(self, file_fixture: FixtureFile) -> None:
        """from_manifest_file should accept both Path and str arguments."""
        manifest_path = file_fixture("manifest.json")

        # Test with str argument
        audiobook_from_str = Audiobook.from_manifest_file(str(manifest_path))

        # Verify the audiobook was created correctly
        assert audiobook_from_str.manifest.metadata.title == "Dungeon Crawler Carl"
        assert (
            audiobook_from_str.manifest.metadata.identifier == "urn:isbn:9798350430943"
        )

        # Test with Path argument
        audiobook_from_path = Audiobook.from_manifest_file(manifest_path)

        # Both should produce the same result
        assert (
            audiobook_from_str.manifest.metadata.title
            == audiobook_from_path.manifest.metadata.title
        )
        assert (
            audiobook_from_str.manifest.metadata.duration
            == audiobook_from_path.manifest.metadata.duration
        )
