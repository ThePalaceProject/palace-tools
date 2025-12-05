from __future__ import annotations

import datetime
import traceback
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import vlc
from textual import log
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal
from textual.widgets import DataTable, Footer, Header, Label, ProgressBar

from palace_tools.models.api.rwpm_audiobook import Manifest


def ms_to_hms(ms: int) -> str:
    """Converts the given number of seconds to a string of format HH:MM:SS."""
    time_delta = str(datetime.timedelta(seconds=ms / 1000.0))

    # Unfortunately timedelta doesn't seem to have an easy way to format the string,
    # so we do a little hackery to get the format we want.
    rest, seconds_str = time_delta.rsplit(":", maxsplit=1)
    seconds_str = f"{float(seconds_str):#06.3f}"
    return f"{rest}:{seconds_str}"


def get_progress(position: float, duration: float) -> float:
    if not duration or duration < 0 or position < 0:
        return 0.0
    return position / duration


@dataclass
class TrackPosition:
    track: Track
    timestamp: int
    tracks: Tracks

    def __hash__(self) -> int:
        return hash((self.track, self.timestamp))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, TrackPosition):
            return False
        return self.track == other.track and self.timestamp == other.timestamp

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, TrackPosition):
            return False
        return self.track > other.track or (
            self.track == other.track and self.timestamp > other.timestamp
        )

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, TrackPosition):
            return False
        return self == other or self > other

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, TrackPosition):
            return False
        return self.track < other.track or (
            self.track == other.track and self.timestamp < other.timestamp
        )

    def __sub__(self, other: TrackPosition) -> int:
        """
        Subtracting two TrackPositions returns the difference in milliseconds
        between the two positions.
        """
        if not isinstance(other, TrackPosition):
            raise ValueError("Can only subtract TrackPositions from each other")

        if self.track == other.track:
            return self.timestamp - other.timestamp

        diff = self.timestamp
        prev_track = self.tracks.previous_track(self.track)
        while prev_track and prev_track != other.track:
            diff += prev_track.duration_ms
            prev_track = self.tracks.previous_track(prev_track)

        if prev_track is None:
            raise ValueError("Can't subtract TrackPositions from each other")

        diff += other.track.duration_ms - other.timestamp
        return diff

    def __add__(self, other: Any) -> TrackPosition:
        """
        Adding an integer to a TrackPosition returns a new TrackPosition
        that has the given number of milliseconds added (or subtracted if
        the number is negative) to the timestamp. If this moves the TrackPosition
        into another track, the timestamp will be adjusted accordingly.
        """
        if not isinstance(other, int):
            raise ValueError("Can only add integers to TrackPosition")

        if other == 0:
            return self

        new_timestamp = self.timestamp + other
        new_track = self.track

        if other < 0:
            while new_timestamp < 0:
                prev_track = self.tracks.previous_track(new_track)
                if prev_track is None:
                    raise ValueError("TrackPosition would be out of bounds")
                new_track = prev_track
                new_timestamp += new_track.duration_ms
        else:
            while new_timestamp > new_track.duration_ms:
                new_timestamp -= new_track.duration_ms
                next_track = self.tracks.next_track(new_track)
                if next_track is None:
                    raise ValueError("TrackPosition would be out of bounds")
                new_track = next_track

        return TrackPosition(
            track=new_track, timestamp=new_timestamp, tracks=self.tracks
        )


@dataclass
class Track:
    href: str
    title: str | None
    duration_ms: int
    index: int

    def __hash__(self) -> int:
        return hash(self.href)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Track):
            return False
        return self.href == other.href

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Track):
            return False
        return self.index > other.index

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Track):
            return False
        return self.index < other.index


class Tracks:
    def __init__(self, manifest: Manifest):
        self.manifest = manifest
        self.tracks = [
            Track(
                href=track.href,
                title=track.title,
                duration_ms=track.duration * 1000,
                index=idx,
            )
            for idx, track in enumerate(self.manifest.reading_order)
        ]

        self.href_to_idx = {track.href: idx for idx, track in enumerate(self.tracks)}
        self.total_duration_ms = 0
        self.calculate_total_duration()

    def by_href(self, href: str) -> Track:
        return self.tracks[self.href_to_idx[href]]

    def previous_track(self, track: int | Track) -> Track | None:
        idx = track.index if not isinstance(track, int) else track
        if idx - 1 < 0:
            return None
        return self.tracks[idx - 1]

    def next_track(self, track: int | Track) -> Track | None:
        idx = track.index if not isinstance(track, int) else track
        if idx + 1 >= len(self.tracks):
            return None
        return self.tracks[idx + 1]

    def __getitem__(self, idx: int) -> Track:
        return self.tracks[idx]

    def __len__(self) -> int:
        return len(self.tracks)

    def __iter__(self) -> Generator[Track]:
        yield from self.tracks

    def calculate_total_duration(self) -> None:
        self.total_duration_ms = sum(track.duration_ms for track in self.tracks)


@dataclass
class Chapter:
    title: str
    position: TrackPosition
    _duration_ms: int | None = None

    @property
    def duration_ms(self) -> int:
        if self._duration_ms is None:
            raise ValueError("Duration not set")
        return self._duration_ms

    @duration_ms.setter
    def duration_ms(self, value: int) -> None:
        self._duration_ms = value

    def __contains__(self, position: TrackPosition) -> bool:
        return self.position <= position < self.position + self.duration_ms


class TableOfContents:
    def __init__(self, manifest: Manifest, tracks: Tracks):
        self.manifest = manifest
        self.tracks = tracks
        self.toc = []

        for entry in self.manifest.toc_in_playback_order:
            track_href, offset = entry.href.split("#t=")
            track = self.tracks.by_href(track_href)

            self.toc.append(
                Chapter(
                    title=entry.title,
                    position=TrackPosition(
                        track=track, timestamp=int(offset) * 1000, tracks=self.tracks
                    ),
                )
            )

        # Make sure the first entry starts at position 0 and
        # track 0, if it doesn't then insert a new implicit first toc
        # entry
        first_entry = self.toc[0]
        if first_entry.position.timestamp != 0 or first_entry.position.track.index != 0:
            self.toc.insert(
                0,
                Chapter(
                    title="Forward",
                    position=TrackPosition(
                        track=self.tracks[0], timestamp=0, tracks=self.tracks
                    ),
                ),
            )

        self.calculate_durations()

    def calculate_durations(self) -> None:
        for idx, entry in enumerate(self.toc):
            if idx + 1 < len(self.toc):
                next_toc_position = self.toc[idx + 1].position
            else:
                next_toc_position = TrackPosition(
                    track=self.tracks[-1],
                    timestamp=self.tracks[-1].duration_ms,
                    tracks=self.tracks,
                )
            entry.duration_ms = next_toc_position - entry.position

    def __getitem__(self, idx: int) -> Chapter:
        return self.toc[idx]

    def __len__(self) -> int:
        return len(self.toc)

    def __iter__(self) -> Generator[Chapter]:
        yield from self.toc

    def next_chapter(self, chapter: Chapter) -> Chapter | None:
        idx = self.toc.index(chapter)
        if idx + 1 >= len(self.toc):
            return None
        return self.toc[idx + 1]

    def previous_chapter(self, chapter: Chapter) -> Chapter | None:
        idx = self.toc.index(chapter)
        if idx - 1 < 0:
            return None
        return self.toc[idx - 1]

    def chapter_for_position(self, position: TrackPosition) -> Chapter:
        for chapter in self.toc:
            if position in chapter:
                return chapter
        raise ValueError(f"No chapter found for position {position}")

    def index(self, chapter: Chapter) -> int:
        return self.toc.index(chapter)


class PalaceMediaPlayer:
    PLAYBACK_SPEEDS = [0.5, 1.0, 1.25, 1.5, 1.75, 2.0]

    def __init__(self, manifest_file: Path):
        if not manifest_file.exists():
            raise FileNotFoundError(f"File {manifest_file} does not exist")

        self.manifest = Manifest.parse_file(manifest_file)
        self.tracks = Tracks(self.manifest)

        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.list_player = self.instance.media_list_player_new()
        self.list_player.set_media_player(self.player)
        self.media_list = self.instance.media_list_new()

        for idx, entry in enumerate(self.tracks):
            media_file = manifest_file.parent / entry.href
            media = self.instance.media_new(media_file)
            media.parse()
            entry.duration_ms = media.get_duration()
            self.media_list.add_media(media)

        self.tracks.calculate_total_duration()
        self.list_player.set_media_list(self.media_list)
        self.toc = TableOfContents(self.manifest, self.tracks)

        self.current_speed = 1.0
        self.current_position = TrackPosition(
            track=self.tracks[0], timestamp=0, tracks=self.tracks
        )
        self.init_handlers()
        self.extra_handlers: list[Callable[[], None]] = []

    def play(self) -> None:
        self.list_player.play()

    def pause(self) -> None:
        self.list_player.pause()

    def next_track(self) -> None:
        next_track = self.tracks.next_track(self.current_position.track)
        if next_track is None:
            return
        self.play_track(next_track)

    def previous_track(self) -> None:
        prev_track = self.tracks.previous_track(self.current_position.track)
        if prev_track is None:
            return
        self.play_track(prev_track)

    def play_track(self, track: Track, offset: int = 0) -> None:
        self.list_player.play_item_at_index(track.index)
        if offset:
            self.player.set_time(int(offset))

        self.current_position.track = track
        self.current_position.timestamp = offset

    def next_chapter(self) -> None:
        current_chapter = self.toc.chapter_for_position(self.current_position)
        next_chapter = self.toc.next_chapter(current_chapter)
        if next_chapter is None:
            return
        self.play_chapter(next_chapter)

    def previous_chapter(self) -> None:
        current_chapter = self.toc.chapter_for_position(self.current_position)
        prev_chapter = self.toc.previous_chapter(current_chapter)
        if prev_chapter is None:
            return
        self.play_chapter(prev_chapter)

    def play_chapter(self, chapter: Chapter) -> None:
        self.play_track(chapter.position.track, chapter.position.timestamp)

    def jump(self, ms: int) -> None:
        new_position = self.current_position + ms
        self.play_track(new_position.track, new_position.timestamp)

    def jump_back(self) -> None:
        self.jump(-30 * 1000)

    def jump_forward(self) -> None:
        self.jump(30 * 1000)

    def playback_speed(self, speed: float) -> float:
        self.current_speed = speed
        self.player.set_rate(self.current_speed)
        return self.current_speed

    def increase_speed(self) -> float:
        if self.current_speed == self.PLAYBACK_SPEEDS[-1]:
            return self.current_speed
        idx = self.PLAYBACK_SPEEDS.index(self.current_speed) + 1
        return self.playback_speed(self.PLAYBACK_SPEEDS[idx])

    def decrease_speed(self) -> float:
        if self.current_speed == self.PLAYBACK_SPEEDS[0]:
            return self.current_speed
        idx = self.PLAYBACK_SPEEDS.index(self.current_speed) - 1
        return self.playback_speed(self.PLAYBACK_SPEEDS[idx])

    def track_position_callback(self, event: vlc.EventType) -> None:
        self.current_position.timestamp = self.player.get_time()

        log("Position callback called")
        log(self.current_position)

        for handler in self.extra_handlers:
            handler()

    def track_changed_callback(self, event: vlc.EventType) -> None:
        media = self.player.get_media()
        idx = self.media_list.index_of_item(media)
        self.current_position.track = self.tracks[idx]
        self.current_position.timestamp = 0

        log("Track changed callback called")
        log(self.current_position)

    def init_handlers(self) -> None:
        event_manager = self.player.event_manager()
        event_manager.event_attach(
            vlc.EventType.MediaPlayerPositionChanged,
            self.track_position_callback,
        )

        event_manager.event_attach(
            vlc.EventType.MediaPlayerMediaChanged,
            self.track_changed_callback,
        )


class MediaPlayerUi(App[None]):
    TITLE = "PALACE - Terminal Edition"
    BINDINGS = [
        ("p", "play", "Play Media"),
        ("s", "stop", "Stop Media"),
        ("n", "next_track", "Next Track"),
        ("b", "previous_track", "Previous Track"),
        ("'", "next_chapter", "Next Chapter"),
        (";", "previous_chapter", "Previous Chapter"),
        ("]", "jump_forward", "Forward 30s"),
        ("[", "jump_back", "Back 30s"),
        ("=", "increase_speed", "Increase Speed"),
        ("-", "decrease_speed", "Decrease Speed"),
        ("q", "quit", "Quit"),
    ]
    CSS_PATH = "palace_terminal.tcss"

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        with Horizontal(id="main"):
            yield DataTable(id="toc")
            yield DataTable(id="tracks")
        with Center(id="book_info_footer", classes="footer"):
            yield Label("", id="title")
            yield Label("", id="author")
            yield Label("", id="identifier")
        with Center(id="chapter_footer", classes="footer"):
            yield Label("Chapter: ", id="chapter_id")
            yield ProgressBar(
                total=1.0, show_eta=False, show_percentage=False, id="chapter_progress"
            )
            yield Label("00:00:00.00", id="chapter_time")
        with Center(id="track_footer", classes="footer"):
            yield Label("Track: ", id="track_id")
            yield ProgressBar(
                total=1.0, show_eta=False, show_percentage=False, id="track_progress"
            )
            yield Label("00:00:00.00", id="track_time")
        with Center(id="overall_footer", classes="footer"):
            yield Label("Overall: ", id="overall_id")
            yield ProgressBar(
                total=1.0, show_eta=False, show_percentage=False, id="overall_progress"
            )
            yield Label("00:00:00.00", id="overall_time")
        with Center(id="speed_footer", classes="footer"):
            yield Label("Speed: ")
            yield Label("1.00", id="speed_label")

        yield Header()
        yield Footer()

    async def action_quit(self) -> None:
        self.player.list_player.stop()
        self.player.extra_handlers.clear()
        self.app.exit()

    def action_play(self) -> None:
        self.player.play()

    def action_stop(self) -> None:
        self.player.pause()

    def action_next_track(self) -> None:
        self.player.next_track()

    def action_previous_track(self) -> None:
        self.player.previous_track()

    def action_next_chapter(self) -> None:
        self.player.next_chapter()

    def action_previous_chapter(self) -> None:
        self.player.previous_chapter()

    def action_jump_back(self) -> None:
        self.player.jump_back()

    def action_jump_forward(self) -> None:
        self.player.jump_forward()

    def action_increase_speed(self) -> None:
        speed = self.player.increase_speed()
        self.query_one("#speed_label", Label).update(f"{speed:.2f}")

    def action_decrease_speed(self) -> None:
        speed = self.player.decrease_speed()
        self.query_one("#speed_label", Label).update(f"{speed:.2f}")

    def on_mount(self) -> None:
        title = self.query_one("#title", Label)
        title.update(f"{self.player.manifest.metadata.title}")
        identifier = self.query_one("#identifier", Label)
        identifier.update(f"{self.player.manifest.metadata.identifier}")
        author = self.query_one("#author", Label)
        if self.player.manifest.metadata.author:
            author.update(f"By: {self.player.manifest.metadata.author}")

        table = self.query_one("#toc", DataTable)
        table.add_column("", key="playing")
        table.add_columns("Chapter", "Duration")
        table.cursor_type = "row"
        for idx, toc_entry in enumerate(self.player.toc):
            table.add_row(
                "  ", toc_entry.title, ms_to_hms(toc_entry.duration_ms), key=str(idx)
            )

        table = self.query_one("#tracks", DataTable)
        table.add_column("", key="playing")
        table.add_columns("Track", "Duration")
        table.cursor_type = "row"
        for idx, track_entry in enumerate(self.player.tracks):
            table.add_row(
                " ",
                track_entry.href,
                ms_to_hms(track_entry.duration_ms),
                key=str(idx),
            )

        self.player.extra_handlers.append(self.update_player_info)

    def progress_update(
        self, progress_type: str, name: str | None, position: int, duration: int
    ) -> None:
        progress = get_progress(position, duration)
        log(
            f"Progress update: {progress_type} {name} pos: {position} dur: {duration} prog: {progress}"
        )

        time_label = self.query_one(f"#{progress_type}_time", Label)
        time_label.update(f"{ms_to_hms(position)} / {ms_to_hms(duration)}")

        progress_bar = self.query_one(f"#{progress_type}_progress", ProgressBar)
        progress_bar.update(progress=progress)

        if name:
            id_label = self.query_one(f"#{progress_type}_id", Label)
            id_label.update(f"{name}")

    def update_player_info(self) -> None:
        try:
            track_position = self.player.current_position.timestamp
            track_duration = self.player.current_position.track.duration_ms
            track = self.player.current_position.track
            track_name = f"Track: {track.href}"
            self.progress_update("track", track_name, track_position, track_duration)
            track_table = self.query_one("#tracks", DataTable)
            self.set_playing_row(track_table, str(track.index))

            chapter = self.player.toc.chapter_for_position(self.player.current_position)
            chapter_position = self.player.current_position - chapter.position
            chapter_duration = chapter.duration_ms
            chapter_name = f"Chapter: {chapter.title}"
            chapter_idx = self.player.toc.index(chapter)
            self.progress_update(
                "chapter", chapter_name, chapter_position, chapter_duration
            )
            toc_table = self.query_one("#toc", DataTable)
            self.set_playing_row(toc_table, str(chapter_idx))

            overall_position = (
                self.player.current_position - self.player.toc[0].position
            )
            overall_duration = self.player.tracks.total_duration_ms
            self.progress_update("overall", None, overall_position, overall_duration)

        except Exception as e:
            log(e)
            log(traceback.format_exc())

    @staticmethod
    def set_playing_row(table: DataTable[str], key: str) -> None:
        for row_key in table.rows.keys():
            if row_key.value == key:
                updated_str = "▶️"
            else:
                updated_str = " "

            table.update_cell(row_key, "playing", updated_str)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        datatable_id = event.control.id
        key = event.row_key
        assert key.value is not None
        if datatable_id == "toc":
            self.player.play_chapter(self.player.toc[int(key.value)])
        elif datatable_id == "tracks":
            self.player.play_track(self.player.tracks[int(key.value)])

    def __init__(self, player: PalaceMediaPlayer):
        super().__init__()
        self.player = player


app = typer.Typer()


def main() -> None:
    app(prog_name="palace-terminal")


@app.command()
def command(
    manifest_file: Path = typer.Argument(
        exists=True,
        readable=True,
        file_okay=True,
        dir_okay=False,
        help="Manifest file to load into player.",
    ),
) -> None:
    player = PalaceMediaPlayer(manifest_file)
    app_ui = MediaPlayerUi(player)
    app_ui.run()


if __name__ == "__main__":
    main()
