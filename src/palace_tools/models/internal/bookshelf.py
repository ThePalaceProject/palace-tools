from palace_tools.models.api.opds2 import OPDS2Feed
from palace_tools.utils.misc import ensure_list


def print_bookshelf_summary(bookshelf: OPDS2Feed) -> None:
    pubs = bookshelf.publications

    print(
        bookshelf.metadata.get("title")
        if hasattr(bookshelf, "metadata")
        else "Bookshelf"
    )
    if not pubs:
        print("  No books on shelf.")
        return

    loans = [pub for pub in pubs if pub.is_loan]
    holds = [pub for pub in pubs if not pub.is_loan]

    print("\n", "  Loans:" if loans else "  No loans.", sep="")
    for p in loans:
        authors = ", ".join([a.name for a in ensure_list(p.metadata.author)])
        print(f"\n    {p.metadata.title}  ({authors})")
        for link in p.acquisition_links:
            print(f"      Fulfillment url: {link.href}")
            for indirect in (
                lnk for lnk in link.indirect_acquisition_links if lnk.get("type")
            ):
                print(f"        Indirect type: {indirect['type']}")

            if hashed_pw := (
                link.properties.get("lcp_hashed_passphrase")
                if link.properties
                else None
            ):
                print(f"      LCP hashed passphrase: {hashed_pw}")
    print("\n", "  Holds:" if holds else "  No holds.", sep="")
    for p in holds:
        print(f"    {p.metadata.title}")
