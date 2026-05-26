from palace.opds.opds2 import Link, Publication, PublicationFeed

from palace.tools.constants import OPDS_ACQ_OPEN_ACCESS_REL, OPDS_ACQ_STANDARD_REL

_ACQUISITION_RELS = {OPDS_ACQ_STANDARD_REL, OPDS_ACQ_OPEN_ACCESS_REL}


def _acquisition_links(publication: Publication) -> list[Link]:
    return [
        link for link in publication.links if _ACQUISITION_RELS.intersection(link.rels)
    ]


def print_bookshelf_summary(bookshelf: PublicationFeed) -> None:
    pubs = bookshelf.publications

    print(str(bookshelf.metadata.title))
    if not pubs:
        print("  No books on shelf.")
        return

    loans = [pub for pub in pubs if _acquisition_links(pub)]
    holds = [pub for pub in pubs if not _acquisition_links(pub)]

    print("\n", "  Loans:" if loans else "  No loans.", sep="")
    for p in loans:
        authors = ", ".join(str(a.name) for a in p.metadata.authors)
        print(f"\n    {p.metadata.title}  ({authors})")
        for link in _acquisition_links(p):
            print(f"      Fulfillment url: {link.href}")
            for indirect in link.properties.indirect_acquisition:
                print(f"        Indirect type: {indirect.type}")

            if hashed_pw := link.properties.lcp_hashed_passphrase:
                print(f"      LCP hashed passphrase: {hashed_pw}")
    print("\n", "  Holds:" if holds else "  No holds.", sep="")
    for p in holds:
        print(f"    {p.metadata.title}")
