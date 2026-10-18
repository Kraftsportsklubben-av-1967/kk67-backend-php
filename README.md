# KK-67 Backend - PHP version

In order to avoid leaking API_KEYS, the backend shall fetch all data from Facebook, Instagram etc.

The backend is a simple PHP server / script.

Facebook and Instagram requests explicitly use **Graph API v26.0**. Meta
[automatically upgrades retired versions](https://developers.facebook.com/docs/graph-api/guides/versioning),
so keep this pin on a supported version rather than relying on that fallback.

An API version upgrade does not guarantee missing captions will be returned.
The backend passes through Meta's media fields; clients must handle absent text.

![PHP](https://img.shields.io/badge/php-%23777BB4.svg?style=for-the-badge&logo=php&logoColor=white)

# Contribute

This server is maintained by Marius Arhaug.

To contribute to this project, follow the guidelines described in the [CONTRIBUTING.md](./CONTRIBUTING.md)

## Endpoints

Currently the REST API\* supports these endpoints:

```
/health     # Get server health (TODO get actual health)
/posts/fb   # Get facebook posts based on .env variables (we want kk67 posts)
/posts/ig   # Get instagram posts --||--

/posts/fb/<pagination_token>   # Get facebook posts based on pagination token
/posts/ig/<pagination_token>   # Get instagram posts --||--
```

> For more info about REST APIs check this [video](https://www.youtube.com/watch?v=-MTSQjw5DrM&t=377s&ab_channel=Fireship).
> Only the first 100 sec is about the concept of REST APIs..

## Production deployment

The `PHP deployment` workflow checks pull requests and pushes to `main`, the
application's default branch. Only a **push to the default branch** can run the
production job, after validation succeeds. Merging a PR triggers deployment;
**direct pushes to `main` also deploy**. Pull requests only validate: they never
receive FTP secrets, connect to FTP, or upload files. There is no manual
deployment trigger or `pull_request_target` workflow.

Configure the encrypted Actions secrets **`FTP_USERNAME`** and **`FTP_PASSWORD`**
before rollout. At rollout, `main` has no branch protection, so the workflow
does not enforce PR review or prevent direct pushes. This is a rollout caveat,
not a deployment blocker. The workflow does not change GitHub protection
settings. Provisioning secrets, merging, and production uploads remain separate
operational actions.

Each job checks out **only this repository** at its event commit, with no
submodules. The uploader, vendored FTPS module, and deployment regression tests
live here under `scripts` and `tests`. CI does not check out another repository,
pin a deployment controller, or fetch deployment scripts at runtime.

### Production package and transport

This application has **no Composer manifest or production dependencies**. PHP
8.3, matching the Docker baseline, lints the package and runs the existing
credential-free smoke check against its actual packaged entry point.
The explicit package contains only:

| Repository source | Deployed filename |
| --- | --- |
| `src/index.php` | `index.php` |
| `src/loader.php` | `loader.php` |

No `.env` files or backups, Git metadata, tests, documentation, Docker/development
tooling, logs, caches, uploads, writable runtime data, or local credentials are
packaged. Existing server-side `.env`, `.htaccess`, `.user.ini`, settings and data
are neither overwritten nor deleted. If Composer or additional runtime files
are introduced, update the reviewed package and tests first; Composer manifests
currently fail closed rather than silently deploying without `vendor`.
Production environment variables and existing host routing must already be
configured. Deployment runs no migrations and changes no server configuration.

The app-local uploader uses **explicit FTPS with required TLS and
certificate verification** to `ftp.c9ry3m6by.service.one`. The destination,
relative to the FTP login home, is **`webroots/r1058768`**. This is not the
account-name breadcrumb shown in the web file manager. CI passes an explicit
`PSCredential` constructed from step-scoped encrypted secrets. Credentials are
not command-line arguments or credential files.

Production jobs are serialized, and a newer push does not cancel an upload
already running. Only these two runtime files are uploaded, with `index.php`
last; **nothing is recursively deleted remotely**. This is not an atomic
release: an interrupted upload can leave a partial file or mixed versions, and
obsolete files are not automatically removed. Entry-point-last ordering reduces
but does not eliminate that window. Roll back with a reviewed revert and another
`main` deployment; any stale-file cleanup needs a separate reviewed
operation.

### Local preview

From this backend repository, with PowerShell 7, `curl.exe` and PHP 8.3+
available:

```powershell
.\scripts\upload-backend-php.ps1 -WhatIf
```

This creates a two-file package under the application's gitignored `build`
directory, lints it, runs the offline smoke test, and previews the upload without
reading credentials, prompting, or connecting to FTP. Its generated package is
removed on success or failure. Use `-AppPath '<backend-worktree>'` to validate a
separate checkout. Do not run without `-WhatIf` unless a live upload is approved.

For a separately approved local upload, credentials default to this repository's
private `.env` beside `README.md`. Node.js **20.12+** parses only `FTP_USERNAME`
and `FTP_PASSWORD`; it does not export or execute other keys. A partial pair
fails before connecting. If the default file is absent or both keys are empty,
the uploader uses a secure credential prompt.

To retain an existing private credential file elsewhere, pass its path without
copying any passwords:

```powershell
.\scripts\upload-backend-php.ps1 -EnvFilePath 'D:\dev\kk67-docker\.env' -WhatIf
```

`-WhatIf` never reads or validates that file. During a real upload, an explicitly
selected missing file fails instead of falling back to the default file or a
prompt. An explicit `-Credential <PSCredential>` overrides the file, even if the
selected path is missing. CI always supplies that explicit credential from its
step-scoped secrets. `-AppPath` changes the packaged code, not the default
credential-file location; use `-EnvFilePath` separately when needed. Never commit
credential files or backups.
