# Contributing

## Get started

# docker-compose

If you want to avoid downloading or chaning your local environment, you can checkout the guide how to setup the frontend and backend for docker-compose [here](https://github.com/Kraftsportsklubben-av-1967/kk67-docker)

1. Clone docker-compose repo and follow the repo guide

```sh
$ git clone git@github.com:Kraftsportsklubben-av-1967/kk67-docker.git
```

2. Set up env variables in a `.env` file **not** to be pushed to repo). Ask **Marius** for key(s).

```sh
FB_USER_KEY=<key>
FB_PAGE_KEY=<key>
FB_USER_ID=<id>
FB_PAGE_ID=<id>
```

## Checks

The smoke check verifies the Graph API version pin and response helpers using
fixtures. It does not contact Facebook or require credentials.

```sh
docker build -t kk67-backend-php .
docker run --rm --entrypoint php kk67-backend-php tests/smoke.php
```

With PHP 8.3+ installed, run `php tests/smoke.php` directly. An optional first
argument selects a packaged `index.php`, so the deployment checks exercise the
flat production layout rather than only the source tree.

The deployment checks use Python's standard library, PowerShell 7, `curl.exe`,
and Node.js 20.12+ (CI uses Node 24). From this repository:

```powershell
python -m unittest discover -s .\tests -p 'test_*.py' -v
.\scripts\upload-backend-php.ps1 -WhatIf
```

`tests\test_upload_backend_php.py` checks the explicit runtime package, validation
failures, symlink rejection, cleanup, and credential-file forwarding using a
mock transport. `tests\test_ftps.py` exercises the real local FTPS module with
fake curl and real Node dotenv parsing: required TLS, stdin-only credentials,
credential precedence, external and missing files, preview isolation, preflight,
encoding, entry-point-last ordering, and failure propagation. No test connects
to FTP. `tests\test_deployment.py` enforces the PR/default-branch boundary and
own-repository-only checkouts.

The workflow runs all three suites, then the real uploader with `-WhatIf`, which
lints the package and executes its PHP smoke check without credentials or an FTP
connection. See the [deployment guide](README.md#production-deployment) before
changing the local scripts or production package.
