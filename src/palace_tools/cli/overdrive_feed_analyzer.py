import json
from enum import Enum
from pathlib import Path
from typing import Any, Set

import typer

from palace_tools.utils.typer import run_typer_app_as_main

COPIES_OWNED = "copies owned"
COPIES_AVAILABLE = "copies available"
COPIES_SHARED = "owned copies shared"
COPIES_UNSHARED = "owned copies unshared"

app = typer.Typer()


@app.command("stats")
def stats(
    input_file: Path = typer.Argument(
        ..., help="Input json file (overdrive feed)", file_okay=True, dir_okay=False
    ),
) -> None:
    """
    This command outputs a json map with some file stats.
    """
    accounts_stats: dict[Any, Any] = {}
    stats: dict[Any, Any] = {}

    with input_file.open("r") as input:
        data = json.load(input)
        identifiers: Set[str] = set()
        identifiers_with_no_availability: Set[str] = set()

        for datum in data:
            availability = datum.get("availabilityV2", None)
            identifier = datum["id"]
            identifiers.add(identifier)
            if not availability:
                print(f"no availabilityV2 found where book id = {identifier}\n")
                identifiers_with_no_availability.add(identifier)
            else:
                accounts = availability["accounts"]
                book_level_copies_owned = availability.get("copiesOwned", 0)
                book_level_copies_available = availability.get("copiesAvailable", 0)
                stats["feed-wide copies owned"] = (
                    stats.get("feed-wide copies owned", 0) + book_level_copies_owned
                )
                stats["feed-wide copies available"] = (
                    stats.get("feed-wide copies available", 0)
                    + book_level_copies_available
                )
                for account in accounts:
                    account_id = str(account["id"])
                    shared = account.get("shared", False)
                    copies_available = account.get("copiesAvailable", 0)
                    copies_owned = account.get("copiesOwned", 0)
                    account_stats = accounts_stats.get(account_id, {})
                    accounts_stats[account_id] = account_stats
                    if shared:
                        account_stats[COPIES_SHARED] = copies_owned + account_stats.get(
                            COPIES_SHARED, 0
                        )
                        account_stats[COPIES_UNSHARED] = account_stats.get(
                            COPIES_UNSHARED, 0
                        )
                    else:
                        account_stats[
                            COPIES_UNSHARED
                        ] = copies_owned + account_stats.get(COPIES_UNSHARED, 0)
                        account_stats[COPIES_SHARED] = account_stats.get(
                            COPIES_SHARED, 0
                        )

                    account_stats[
                        COPIES_AVAILABLE
                    ] = copies_available + account_stats.get(COPIES_AVAILABLE, 0)
                    account_stats[COPIES_OWNED] = copies_owned + account_stats.get(
                        COPIES_OWNED, 0
                    )

        stats["file_name"] = input.name
        stats["unique identifiers"] = len(identifiers)
        stats["total book entries in file"] = len(data)
        stats["total identifiers without availability"] = len(identifiers_with_no_availability)
        stats["identifiers without availability"] = list(identifiers_with_no_availability)

    accounts_stats["total advantage plus copies shared"] = sum(
        [x[COPIES_SHARED] for x in accounts_stats.values()]
    )
    stats["accounts"] = accounts_stats

    print(json.dumps(stats, sort_keys=True, indent=4))


class SharedStatus(Enum):
    ALL = "all"
    SHARED = "shared"
    UNSHARED = "unshared"


@app.command("list-identifiers")
def list_identifiers(
    input_file: Path = typer.Argument(
        ..., help="Input json file (overdrive feed)", file_okay=True, dir_okay=False
    ),
    output_file: Path = typer.Argument(
        ..., help="Output file", writable=True, file_okay=True, dir_okay=False
    ),
    filter_by_shared: SharedStatus = typer.Option(
        SharedStatus.ALL, "-s", "--shared", help="Is it shared? By default both shared and "
                                                 "unshared are included."
    ),
    unique_to_filtered_account: bool = typer.Option(
        False,
        "-U",
        "--unique-to-filtered-account",
        help="Filter out identifiers that are unique to the filtered account if set.",
    ),
    filter_by_account_id: int = typer.Option(
        None,
        "-a",
        "--filter-by-account-id",
        help="The account id to match on",
    ),
    filter_by_formats: str = typer.Option(
        None,
        "-f",
        "--format",
        help="The format to match on",
    ),
) -> None:
    """
    This command produces a list of identifiers according to different criteria
    """
    identifiers = set()
    all_formats: dict[str, int] = {}
    with input_file.open("r") as input:
        data = json.load(input)
        for datum in data:
            availability = datum.get("availabilityV2", None)
            title_id = datum["id"]
            if availability:
                accounts = availability["accounts"]
                for account in accounts:
                    acc_id = account["id"]
                    account_filter_matches = (
                        True
                        if filter_by_account_id is None
                        or (filter_by_account_id == acc_id)
                        else False
                    )
                    unique_to_filtered_account_matches = (
                        True
                        if not unique_to_filtered_account
                        or (unique_to_filtered_account and len(accounts) == 1)
                        else False
                    )

                    account_shared_status = SharedStatus.SHARED if account.get("shared",
                                                                               False) else SharedStatus.UNSHARED
                    shared_filter_matches = (
                        True
                        if filter_by_shared == SharedStatus.ALL
                        or (account_shared_status == filter_by_shared)
                        else False
                    )
                    format_filter_matches = True
                    formats = [x["id"] for x in datum.get("formats",[])]
                    formats_to_match = (
                        [] if not filter_by_formats else filter_by_formats.split(",")
                    )

                    for f in formats:
                        all_formats[f] = all_formats.get(f, 0) + 1

                    if filter_by_formats:
                        matching_formats = [x for x in formats if x in formats_to_match]
                        format_filter_matches = (
                            True if len(matching_formats) > 0 else False
                        )

                    if (
                        account_filter_matches
                        and unique_to_filtered_account_matches
                        and shared_filter_matches
                        and format_filter_matches
                    ):
                        identifiers.add(title_id)

    with output_file.open("w") as output:
        sorted_identifiers = sorted(identifiers)
        for identifier in sorted_identifiers:
            output.write(identifier + "\n")

    print(
        f"There are {len(identifiers)} identifiers matching the criteria: "
        f"shared={filter_by_shared}, "
        f"format={filter_by_formats}, "
        f"account_id={filter_by_account_id}, "
        f"unique_to_account={unique_to_filtered_account}.  The "
        f"specific identifiers can be found in the output file {output_file} \n"
        f"available formats: {all_formats}"
    )


def main() -> None:
    run_typer_app_as_main(app, prog_name="overdrive_feed_analyzer")


if __name__ == "__main__":
    main()
