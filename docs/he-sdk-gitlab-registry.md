# HE SDK package registry guide

`he-sdk` will be published to the private, PyPI-compatible package registry of
the `nhatcao99uetwork/k3s-demo-app` GitLab project when its release tag pipeline
succeeds. It is not stored in Docker Hub, and it is not currently published to
the public `pypi.org` index.

GitLab accepts either a numeric project ID or a URL-encoded project path in
package API URLs. The filled project identifier for this repository is:

```text
nhatcao99uetwork%2Fk3s-demo-app
```

The resulting package index is:

```text
https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple
```

## Publish version 0.3.0 from CI

The `publish-sdk-gitlab` job in `.gitlab-ci.yml` publishes the wheel only from
a semantic-version tag. It uses GitLab's short-lived `CI_JOB_TOKEN`; do not
create or save a publishing token for this job.

Make sure the version in `pyproject.toml` is `0.3.0`, merge the code, and push
the matching tag:

```sh
git tag -a v0.3.0 -m "Publish he-sdk 0.3.0"
git push origin v0.3.0
```

The publish job deliberately fails if the tag and package version differ.
GitLab does not allow the same package name and version to be uploaded twice,
so bump `pyproject.toml` and create a new tag for every release.

After the job succeeds, find the wheel under **Deploy > Package registry** in
the `k3s-demo-app` project.

## Install inside another GitLab CI job

The token in the original command is the current job's built-in
`CI_JOB_TOKEN`. No secret variable needs to be prepared:

```sh
python -m pip install --no-deps \
  --index-url "https://gitlab-ci-token:${CI_JOB_TOKEN}@gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  he-sdk==0.3.0
```

If the consuming pipeline belongs to a different private project, allow that
project or group in the package project's **Settings > CI/CD > Job token
permissions** allowlist.

## Prepare a read-only token for another server

Do not copy a CI job token to a server: it is temporary and tied to a running
job. In the `k3s-demo-app` project, open **Settings > Repository > Deploy
tokens**, then create a token with:

- name: `he-sdk-reader`;
- an appropriate expiry date;
- scope: `read_package_registry` only.

Copy both values shown by GitLab: the deploy-token **username** and the token
itself. GitLab often generates a username such as
`gitlab+deploy-token-123456`; use the exact displayed value.

For a quick test, supply those values through environment variables. The
username is not `gitlab-ci-token` in this case:

```sh
export HE_SDK_GITLAB_USER='gitlab+deploy-token-123456'
read -rsp 'GitLab deploy token: ' HE_SDK_GITLAB_TOKEN
printf '\n'

python -m pip install --no-deps \
  --index-url "https://${HE_SDK_GITLAB_USER}:${HE_SDK_GITLAB_TOKEN}@gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  he-sdk==0.3.0

unset HE_SDK_GITLAB_TOKEN
```

The expanded URL may be visible briefly to other users in the process list.
For a durable server setup, store the credentials in the service account's
`~/.netrc` instead and restrict the file to that account:

```text
machine gitlab.com
login gitlab+deploy-token-123456
password REPLACE_WITH_DEPLOY_TOKEN
```

```sh
chmod 600 ~/.netrc
python -m pip install --no-deps \
  --index-url "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  he-sdk==0.3.0
```

Never commit `.netrc`, a deploy token, or an index URL containing credentials.
Rotate the deploy token if it appears in logs or shell history.

## Install the OpenFHE runtime and test a Python file

The private wheel contains the SDK wrapper but deliberately has no mandatory
heavy dependency. On a supported Linux server, create a virtual environment,
install OpenFHE from public PyPI, then install the private wheel:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --index-url https://pypi.org/simple \
  openfhe==1.5.1.0.24.4
python -m pip install --no-deps \
  --index-url "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app/packages/pypi/simple" \
  he-sdk==0.3.0
```

The last command assumes the deploy-token credentials are in `~/.netrc`.
Then create `test_he_sdk.py`:

```python
from he_sdk import HESession


with HESession.create(backend="openfhe") as he:
    encrypted = he.encrypt([1.0, 2.0, 3.0, 4.0])
    encrypted_result = he.mean(encrypted)
    print(he.decrypt(encrypted_result))
```

Run it without Docker or K3s:

```sh
python test_he_sdk.py
```

For the separate CUDA/FIDESlib plugin package, build, publish and install
`he-sdk-fides==0.1.0` using the process in `he-sdk-fides.md`. Do not install the
stock `openfhe` Python distribution in that GPU environment.

## Optional: look up the numeric project ID

The encoded path above is already a valid project identifier, so a numeric ID
is unnecessary. If a tool insists on a number, create a short-lived GitLab
access token with `read_api`, keep it out of the command line, and run:

```sh
read -rsp 'GitLab API token: ' GITLAB_API_TOKEN
printf '\n'
curl --fail --silent --show-error \
  --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
  "https://gitlab.com/api/v4/projects/nhatcao99uetwork%2Fk3s-demo-app" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])'
unset GITLAB_API_TOKEN
```
