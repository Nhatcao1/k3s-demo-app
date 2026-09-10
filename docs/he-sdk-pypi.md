# Publish `he_looming_sdk` to PyPI

The distribution name is `he_looming_sdk`; PyPI normalizes and displays it as
`he-looming-sdk`. The installed Python module remains `he_sdk`, so developer
code continues to use:

```python
from he_sdk import HESession
```

This staging release deliberately does not declare a license. PyPI accepts
packages without license metadata, but publishing there does not grant users a
license to copy, modify, or redistribute the source.

## One-time PyPI preparation

Before pushing the first release tag, create a PyPI API token. Because the
`he-looming-sdk` project does not exist yet, the first token must be scoped to
the entire PyPI account. After the first successful release, replace it with a
new token scoped only to the created `he-looming-sdk` project.

In the GitLab project, open **Settings > CI/CD > Variables** and add:

```text
Key: PYPI_API_TOKEN
Value: pypi-<the token copied from PyPI>
Type: Variable
Visibility: Masked and hidden
Protect variable: enabled
Expand variable reference: disabled
```

Protect the GitLab tag pattern `v*` and allow only Maintainers to create it.
The protected token is otherwise unavailable to the release pipeline. Never
put the token in `.gitlab-ci.yml`, a shell command, repository file, or job log.

The project name was checked against the PyPI JSON API before this release and
was not registered. The `publish-sdk-pypi` job authenticates as `__token__`
with `PYPI_API_TOKEN`; the variable is required only in the tag pipeline.

## Release

First merge and verify the `main` pipeline. Protect the `v*` tag pattern so
only Maintainers can publish, then tag the exact commit on `origin/main`:

```sh
git fetch origin main
git tag -a v0.3.1 origin/main -m "Publish he_looming_sdk 0.3.1"
git push origin v0.3.1
```

The same tag builds one wheel and publishes it to both public PyPI and the
project's private GitLab package registry. The tag must match the version in
`pyproject.toml`; released versions are immutable, so bump the version before
every later release.

## Install

After both publish jobs succeed:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install he_looming_sdk==0.3.1
python -c 'import he_sdk; print(he_sdk.__version__)'
```

The core package has no mandatory dependency. For the OpenFHE local backend on
a supported Linux server, also install:

```sh
python -m pip install openfhe==1.5.1.0.24.4
```

Do not publish `he-sdk-fides` to public PyPI yet. Its native wheel remains in
the private GitLab registry and the immutable GPU image until it passes runtime
acceptance on the K3s T4 node.
