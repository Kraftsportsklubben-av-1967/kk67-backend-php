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
