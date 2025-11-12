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

### pyenv

[pyenv](https://github.com/pyenv/pyenv) lets you easily switch between multiple versions of Python. It can be
[installed](https://github.com/pyenv/pyenv-installer) using the command `curl https://pyenv.run | bash`. You can then
install the version of Python you want to work with.

It is recommended that [pyenv-virtualenv](https://github.com/pyenv/pyenv-virtualenv) be used to allow `pyenv`
to manage _virtual environments_ in a manner that can be used by the [poetry](#poetry) tool. The `pyenv-virtualenv`
plugin can be installed by cloning the relevant repository into the `plugins` subdirectory of your `$PYENV_ROOT`:

```sh
mkdir -p $PYENV_ROOT/plugins
cd $PYENV_ROOT/plugins
git clone https://github.com/pyenv/pyenv-virtualenv
```

After cloning the repository, `pyenv` now has a new `virtualenv` command:

```sh
$ pyenv virtualenv
pyenv-virtualenv: no virtualenv name given.
```

### Poetry

This project uses [poetry](https://python-poetry.org/) for dependency management.
If you plan to work on this project, you will need `poetry`.

Poetry can be installed using the command `curl -sSL https://install.python-poetry.org | python3 -`.

More information about installation options can be found in the
[poetry documentation](https://python-poetry.org/docs/master/#installation).

## Installation

This package is not currently available oon PyPI, but it can be installed and run locally in a couple of
different ways, depending on your needs.

### Installing the CLI Tools globally with `pipx`

Installing with `pipx` will be most conducive to running the CLI Tools from any directory.

If you don't already have `pipx` installed, you can get installation instructions
[here](https://github.com/pypa/pipx?tab=readme-ov-file#install-pipx).

```shell
pipx install git+https://github.com/ThePalaceProject/palace-tools.git
```

or, if you wish to install a particular branch or commit, you can do something like this
(more details about [installing from VCS here](https://github.com/pypa/pipx?tab=readme-ov-file#installing-from-source-control)):

```shell
pipx install git+https://github.com/ThePalaceProject/palace-tools.git@branch-or-commit
```

If installation is successful, `pipx` will list the apps that are installed with the package.

### Running CLI Tools from a cloned project

- Clone the repository.
- Change into the cloned directory.
- Run `pyenv virtualenv <python-version> <virtualenv-name>` to create a Python virtual environment.
- Run `pyenv local <virtualenv-name>` to use that virtual environment whenever in the cloned directory.
- Run `poetry install` to install the project dependencies and the CLI tools into the virtual environment.

At this point, you should be able to run the CLI tools using `poetry run <cli-command-and-args>`.
