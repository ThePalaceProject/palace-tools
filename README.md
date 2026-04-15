# Palace Tools 🛠️

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

## What's included

### CLI Tools

- `audiobook-manifest-summary` (`summarize_rwpm_audio_manifest.py`)
    - Produce a summary description from a [Readium Web Publication Manifest (RWPM)](https://github.com/readium/webpub-manifest)
manifest conforming to the [Audiobook Profile](https://github.com/readium/webpub-manifest/blob/master/profiles/audiobook.md).
- `fetch-lcp`
    - `audiobook-manifest`
        - Given an LCP audiobook fulfillment URL, retrieve it and store/print its manifest.
    - `files`
        - Given an LCP audiobook fulfillment URL, retrieve and store the lcp and lcpl files.
- `patron-bookshelf`
    - Print a patron's bookshelf as either a summary or in full as JSON.
- `validate-audiobook-manifests`
    - Validate a directory of RWPM audiobook manifests printing any errors found.
- `palace-terminal`
    - A toy terminal based media player that can be used to play audiobooks from
      a local directory containing audiobook manifests and their associated media files.
    - Note: This application uses `python-vlc` which requires VLC to be installed on
      the system. The VLC installation can be found [here](https://www.videolan.org/vlc/).
- `download-feed` - Download various feeds for local inspection.
    - `opds2`
        - Download an OPDS2 / OPDS2 + ODL feed.
    - `overdrive`
        - Download Overdrive feeds.
    - `axis`
        - Download B&T Axis 360 availability feed.
- `validate-feed` - Validate feeds.
    - `opds2`
        - Validate an OPDS2 feed
    - `opds2-odl`
        - Validate an OPDS2 + ODL feed
- `import-libraries-from-csv`
    - Import libraries from a csv to ease the burden of setting up CMs with many libraries.
    - Note: there is a sample CSV file in the ./samples/ directory that shows the expected format of the CSV file.

### Library Support

- Models for parsing and processing manifests in the
[Audiobook Profile](https://github.com/readium/webpub-manifest/blob/master/profiles/audiobook.md) of the
[Readium Web Publication Manifest (RWPM)](https://github.com/readium/webpub-manifest) specification.

## Working as a developer on this project

### uv

This project uses [uv](https://docs.astral.sh/uv/) for Python and dependency management.
If you plan to work on this project, you will need `uv`.

uv can be installed with `curl -LsSf https://astral.sh/uv/install.sh | sh`. See the
[uv documentation](https://docs.astral.sh/uv/getting-started/installation/) for other
installation options.

Once uv is installed, you can install the required Python version with:

```sh
uv python install 3.12
```

## Installation

This package is [published to PyPI](https://pypi.org/project/palace-tools/), and can also be
installed and run locally from a clone of the repository.

### Installing the CLI Tools globally with `pipx`

Installing with `pipx` will be most conducive to running the CLI Tools from any directory.

If you don't already have `pipx` installed, you can get installation instructions
[here](https://github.com/pypa/pipx?tab=readme-ov-file#install-pipx).

```shell
pipx install palace-tools
```

Alternatively, you can install directly from the git repository, for example to try a
particular branch or commit (more details about
[installing from VCS here](https://github.com/pypa/pipx?tab=readme-ov-file#installing-from-source-control)):

```shell
pipx install git+https://github.com/ThePalaceProject/palace-tools.git@branch-or-commit
```

If installation is successful, `pipx` will list the apps that are installed with the package.

### Running CLI Tools from a cloned project

- Clone the repository.
- Change into the cloned directory.
- Run `uv sync --all-groups` to install the project dependencies and the CLI tools into a
  `.venv` virtual environment.

At this point, you should be able to run the CLI tools using `uv run <cli-command-and-args>`.
