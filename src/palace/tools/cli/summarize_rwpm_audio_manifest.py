#!/usr/bin/env python3

from __future__ import annotations

import textwrap
from pathlib import Path

import typer

from palace.tools.models.internal.rwpm_audio.audiobook import Audiobook
from palace.tools.utils.datetime import seconds_to_hms
from palace.tools.utils.typer import run_typer_app_as_main

app = typer.Typer()


def main() -> None:
    run_typer_app_as_main(app, prog_name="summarize-manifest")


@app.command()
def command(
    manifest_file: Path = typer.Argument(...),
) -> None:
    audiobook = Audiobook.from_manifest_file(manifest_file)
    print(
        text_with_time_delta(
            f'Title: "{audiobook.manifest.metadata.title}"',
            delta_secs=audiobook.manifest.metadata.duration,
        ),
        end="\n\n",
    )
    print_audio_summary(audiobook)
    print_track_summary(audiobook)
    print_toc_audio_segment_summary(audiobook)


def format_delta(delta: int | float, delta_suffix: str | None = None) -> str:
    seconds_str = f"{delta:.3f}".rstrip("0").rstrip(".")
    delta_str = f"{seconds_str}s / {seconds_to_hms(delta)}"
    if delta_suffix:
        delta_str += f" ({delta_suffix})"
    return delta_str


def text_with_time_delta(
    text: str,
    delta_secs: int | float,
    delta_label: str = "duration",
    delta_suffix: str | None = None,
    second_delta: int | float | None = None,
    second_delta_suffix: str | None = None,
) -> str:
    """Append a time delta in seconds and hours:minutes:seconds to some label text.

    An optional second delta can be appended to the time delta.

    :param text: The label text.
    :param delta_secs: The duration in seconds.
    :param delta_label: (Optional) Label characterizing the time delta.
    :param delta_suffix: (Optional) Another label characterizing `delta_secs`.
    :param second_delta: (Optional) second duration in seconds.
    :param second_delta_suffix: (Optional) Label characterizing `second_delta`.
    :return: The label text with the duration appended.
    """
    delta_suffix = delta_suffix if second_delta else None
    text = f"{text} - {delta_label}: {format_delta(delta_secs, delta_suffix)}"
    if second_delta:
        text += f" - {format_delta(second_delta, second_delta_suffix)}"

    return text


def print_audio_summary(audiobook: Audiobook) -> None:
    print(
        text_with_time_delta(
            "Audiobook ToC-based total duration",
            delta_secs=audiobook.toc_total_duration,
            delta_suffix="manifest",
            second_delta=audiobook.toc_actual_total_duration,
            second_delta_suffix="actual",
        ),
        text_with_time_delta(
            f"Number of tracks: {len(audiobook.manifest.reading_order)}",
            delta_secs=sum(
                track.duration for track in audiobook.manifest.reading_order
            ),
            delta_label="total duration",
            delta_suffix="manifest",
            second_delta=sum(
                track.actual_duration for track in audiobook.manifest.reading_order
            ),
            second_delta_suffix="actual",
        ),
        text_with_time_delta(
            f"Audio segments: {sum(len(toc.audio_segments) for toc in audiobook.enhanced_toc_in_playback_order)}",
            delta_secs=sum(
                sum(seg.duration for seg in toc.audio_segments)
                for toc in audiobook.enhanced_toc_in_playback_order
            ),
            delta_label="total duration",
            delta_suffix="manifest",
            second_delta=sum(
                sum(seg.actual_duration for seg in toc.audio_segments)
                for toc in audiobook.enhanced_toc_in_playback_order
            ),
            second_delta_suffix="actual",
        ),
        sep="\n",
    )
    if segments := audiobook.pre_toc_unplayed_audio_segments:
        print(
            text_with_time_delta(
                "<*> Un-played audio segments (before first ToC segment): "
                f"{len(segments)}",
                delta_secs=sum(s.duration for s in segments),
                delta_label="total duration",
            ),
        )
    print("\n")


def print_track_summary(audiobook: Audiobook) -> None:
    print(
        "Tracks (from manifest `reading_order`):",
        *[
            text_with_time_delta(
                f'  #{i} "{track.title}" {track.href}',
                delta_secs=track.duration,
                delta_suffix="manifest",
                second_delta=track.actual_duration,
                second_delta_suffix="actual",
            )
            for i, track in enumerate(audiobook.manifest.reading_order)
        ],
        sep="\n",
        end="\n\n\n",
    )


def print_toc_audio_segment_summary(audiobook: Audiobook) -> None:
    if segments := audiobook.pre_toc_unplayed_audio_segments:
        print(
            text_with_time_delta(
                "<*> Un-played audio segments (before first ToC segment):",
                delta_secs=sum(s.duration for s in segments),
            ),
            *[
                f"""   {
                    text_with_time_delta(
                        f'Track "{s.track.title}" {s.track.href} from {s.start} to {s.end}',
                        delta_secs=s.duration
                    )
                }"""
                for s in segments
            ],
            sep="\n",
            end="\n\n\n",
        )
    for i, toc in enumerate(audiobook.enhanced_toc_in_playback_order):
        indent = " " * toc.depth * 2
        print(
            textwrap.indent(
                text_with_time_delta(
                    f'ToC Entry #{i} "{toc.title}"',
                    delta_secs=toc.duration,
                    delta_label="total duration",
                    delta_suffix="manifest",
                    second_delta=toc.actual_duration,
                    second_delta_suffix="actual",
                ),
                prefix=indent,
            )
        )
        print(
            textwrap.indent(
                text_with_time_delta(
                    f"href: {toc.href}",
                    delta_secs=toc.audio_segments[0].start,
                    delta_label="offset",
                ),
                prefix=indent + " " * 10,
            )
        )
        print(
            textwrap.indent(
                f"Number of tracks: {len(toc.audio_segments)}", prefix=indent
            )
        )

        for s in toc.audio_segments:
            message = f'Track "{s.track.title}" {s.track.href} from '

            if s.end_actual != 0:
                message += f"\n{s.start} ({seconds_to_hms(s.start)}) to {s.end}/{s.end_actual:.2f} ({seconds_to_hms(s.end)}/{seconds_to_hms(s.end_actual)})"
            else:
                message += f"{s.start} ({seconds_to_hms(s.start)}) to {s.end} ({seconds_to_hms(s.end)})"

            print(
                textwrap.indent(
                    text_with_time_delta(
                        message,
                        delta_secs=s.duration,
                        delta_suffix="manifest",
                        second_delta=s.actual_duration,
                        second_delta_suffix="actual",
                    ),
                    prefix=indent + " " * 3,
                )
            )
        print("")


if __name__ == "__main__":
    main()
