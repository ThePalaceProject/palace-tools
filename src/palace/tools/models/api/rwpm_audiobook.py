from __future__ import annotations

import datetime
import sys
from collections.abc import Generator, Sequence
from functools import cached_property

from pydantic import BaseModel, Field, model_validator

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


class ToCEntry(BaseModel):
    href: str
    title: str
    children: Sequence[ToCEntry] | None = None
    # Computed properties.
    track_href: str = ""
    track_offset: int = 0

    @model_validator(mode="after")
    def computed_values(self) -> Self:
        self.track_href, offset = self.href.split("#t=")
        self.track_offset = int(offset)
        return self

    def toc_in_playback_order(self) -> Generator[ToCEntry]:
        """Iterator yielding all ToCEntries in the hierarchy, in the order they appear in the manifest."""
        yield self
        if self.children:
            for child in self.children:
                yield from child.toc_in_playback_order()

    @classmethod
    def from_track(cls, track: AudioTrack, default_title: str = "Track") -> Self:
        """Create a ToCEntry from an AudioTrack."""
        toc_href = f"{track.href}#t=0"
        toc_title = track.title or default_title
        return cls(href=toc_href, title=toc_title)


ToCEntries = Sequence[ToCEntry]


class AudioTrackEncryption(BaseModel):
    scheme: str
    algorithm: str
    profile: str


class AudioTrackProperties(BaseModel):
    encrypted: AudioTrackEncryption | None = None


class AudioTrack(BaseModel):
    title: str | None = None
    href: str
    content_type: str = Field(..., alias="type")
    duration: int  # in seconds
    bitrate: int | None = None
    properties: AudioTrackProperties | None = None

    # Optional property, initialized after the model is created, if
    # we have the source file, this is the actual duration as read from the
    # audio file.
    actual_duration: float = 0.0


class ManifestMetadata(BaseModel):
    object_type: str = Field(..., alias="@type")
    identifier: str
    title: str
    author: str | list[str] | None = None
    publisher: str
    published: datetime.datetime
    language: str
    modified: datetime.datetime
    duration: int


class Manifest(BaseModel):
    context: str = Field(..., alias="@context")
    metadata: ManifestMetadata
    # TODO: links property
    reading_order: list[AudioTrack] = Field(..., alias="readingOrder")
    toc: Sequence[ToCEntry] | None = None

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        # Ensure that there are no duplicate ToC `href`s.
        seen_hrefs = set()
        for entry in self.toc_in_playback_order:
            if entry.href in seen_hrefs:
                continue
                # TODO: raise ValueError(f"Duplicate ToC `href` found: {entry.href}")
            seen_hrefs.add(entry.href)
        return self

    @cached_property
    def effective_toc(self) -> Sequence[ToCEntry]:
        return self.toc or [
            ToCEntry.from_track(track=track, default_title=f"Track {n}")
            for n, track in enumerate(self.reading_order, start=1)
        ]

    @property
    def toc_in_playback_order(self) -> Generator[ToCEntry]:
        """Iterator yielding all ToC entries in the order that they appear in the manifest.

        If there is no `toc` object (or it is empty), we will construct
        the ToC using the manifest's `readingOrder`.
        """
        for entry in self.effective_toc:
            yield from entry.toc_in_playback_order()
