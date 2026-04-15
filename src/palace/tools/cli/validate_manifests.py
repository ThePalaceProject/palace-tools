import json
from pathlib import Path
from textwrap import indent

import typer
from pydantic import ValidationError

from palace.tools.cli.summarize_rwpm_audio_manifest import text_with_time_delta
from palace.tools.models.internal.rwpm_audio.audiobook import Audiobook
from palace.tools.utils.datetime import seconds_to_hms
from palace.tools.utils.typer import run_typer_app_as_main

app = typer.Typer()


def main() -> None:
    run_typer_app_as_main(app, prog_name="validate-audiobook-manifests")


@app.command()
def command(
    manifest_dir: Path = typer.Argument(
        exists=True,
        readable=True,
        file_okay=False,
        dir_okay=True,
        help="Directory to look for manifests in. All .json "
        "files in this directory and its subdirectories will be processed.",
    ),
    language: str = typer.Option(
        None,
        "--language",
        "-l",
        help="Language code to filter by (en, da, es, etc)",
        metavar="LANG",
    ),
) -> None:
    for manifest_file in manifest_dir.rglob("*.json"):
        errors = []
        try:
            audiobook = Audiobook.from_manifest_file(manifest_file)

            manifest = audiobook.manifest

            for track in manifest.reading_order:
                if (
                    track.actual_duration
                    and abs(track.duration - track.actual_duration) > 1
                ):
                    errors.append(
                        f"Track {track.title} ({track.href}) duration ({seconds_to_hms(track.duration)}) does not match "
                        f"actual file duration ({seconds_to_hms(track.actual_duration)})"
                    )

            manifest_duration = manifest.metadata.duration
            toc_total_duration = audiobook.toc_total_duration
            track_total_duration = sum(
                track.duration for track in audiobook.manifest.reading_order
            )
            track_actual_total_duration = sum(
                track.actual_duration for track in audiobook.manifest.reading_order
            )
            segments_total_duration = sum(
                sum(seg.duration for seg in toc.audio_segments)
                for toc in audiobook.enhanced_toc_in_playback_order
            )

            if (
                toc_total_duration != track_total_duration
                or toc_total_duration != segments_total_duration
            ):
                error = (
                    f"Manifest duration ({seconds_to_hms(manifest_duration)}) does not match "
                    f"ToC duration ({seconds_to_hms(toc_total_duration)}) does not match "
                    f"track duration ({seconds_to_hms(track_total_duration)}) or "
                    f"audio segments duration ({seconds_to_hms(segments_total_duration)})"
                )
                if track_actual_total_duration:
                    error += f" or actual track duration ({seconds_to_hms(round(track_actual_total_duration))})"
                errors.append(error)
            if segments := audiobook.pre_toc_unplayed_audio_segments:
                errors.append(
                    text_with_time_delta(
                        "Un-played audio segments (before first ToC segment): "
                        f"{len(segments)}",
                        delta_secs=sum(s.duration for s in segments),
                        delta_label="total duration",
                    ),
                )

            reading_order_hrefs = set()
            for track in audiobook.manifest.reading_order:
                if track.href in reading_order_hrefs:
                    errors.append(f"Duplicate ReadingOrder `href` found: {track.href}")
                reading_order_hrefs.add(track.href)

            if audiobook.manifest.toc:
                tock_hrefs = set()
                for toc_entry in audiobook.manifest.toc:
                    href_without_fragment = toc_entry.href.rsplit("#", maxsplit=1)[0]
                    if toc_entry.href in tock_hrefs:
                        errors.append(f"Duplicate ToC `href` found: {toc_entry.href}")
                    if href_without_fragment not in reading_order_hrefs:
                        errors.append(
                            f"ToC `href` not found in readingOrder: {href_without_fragment}"
                        )
                    tock_hrefs.add(toc_entry.href)

                for toc_entry in audiobook.manifest.toc:
                    if toc_entry.children:
                        errors.append(f"ToC entry has children: {toc_entry.href}")

        except ValidationError as e:
            errors.append(f"{e}")

        if errors:
            manifest_raw = json.loads(manifest_file.read_text())
            manifest_metadata = manifest_raw.get("metadata", {})
            manifest_identifier = manifest_metadata.get("identifier")
            manifest_language = manifest_metadata.get("language")

            if manifest_language and language and manifest_language != language:
                continue

            if manifest_identifier and not manifest_identifier.startswith("urn:isbn:"):
                continue

            print(f"File: {manifest_file} ({manifest_language})")
            for key, value in manifest_metadata.items():
                if key in {
                    "identifier",
                    "title",
                    "subtitle",
                    "author",
                    "publisher",
                }:
                    print(f"  {str(key).capitalize()}: {value}")
            print("\n".join(indent(e, "     ") for e in errors))
            print()


if __name__ == "__main__":
    main()
