# K3s demo application

A small visit-counter application used to learn the complete GitLab CI → GitLab
Container Registry → GitOps → Argo CD → K3s delivery path.

## Components

- `web`: static HTML served by Nginx
- `api`: Flask/Gunicorn HTTP API
- Redis: supplied by the GitOps repository

The browser requests `/api/visit`. Traefik routes `/api` to the API service and
all other paths to the web service. The API increments a Redis-backed counter.

## Pipeline

The GitLab pipeline:

1. validates the required repository files;
2. runs API unit tests;
3. builds the web and API images in parallel with rootless BuildKit;
4. pushes immutable images on the default branch.

For commit `abc12345`, the resulting images are:

```text
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/web:abc12345
registry.gitlab.com/nhatcao99uetwork/k3s-demo-app/api:abc12345
```

The matching tags must then be promoted in
`k3s-demo-gitops/apps/counter/overlays/<environment>/kustomization.yaml`.

## Local API test

```sh
cd api
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Local container build

```sh
docker build -t k3s-demo-web:local web
docker build -t k3s-demo-api:local api
```

No registry credentials or deployment secrets belong in this repository.
