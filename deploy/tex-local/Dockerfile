# TEX Engine - local test image (Frappe v16.36.1 + payments + kamra/TEX).
#
# FOR LOCAL TESTING ONLY: developer_mode on, Werkzeug dev server, demo users with
# well-known passwords. Never expose it to the internet or use it for real data.
#
# Build context = repository root (docker-compose.yml sets this up):
#   docker compose -f deploy/tex-local/docker-compose.yml build
# Files excluded from the context: deploy/tex-local/Dockerfile.dockerignore
#
# Behind a TLS-intercepting proxy, pass its root CA as the optional BuildKit secret
# "extra_ca" (see docker-compose.extra-ca.yml); it is used while downloading and is
# never written into the image. Proxies themselves go through Docker's predefined
# build args (HTTP_PROXY / HTTPS_PROXY / NO_PROXY) or Docker Desktop's proxy settings.

ARG PYTHON_IMAGE=python:3.14-slim-bookworm
ARG NODE_IMAGE=node:24-bookworm-slim

FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE}

ARG FRAPPE_REPO=https://github.com/frappe/frappe
ARG FRAPPE_BRANCH=v16.36.1
ARG PAYMENTS_REPO=https://github.com/frappe/payments
ARG PAYMENTS_BRANCH=version-16
ARG BENCH_VERSION=5.31.0

ENV LANG=C.UTF-8 \
	LC_ALL=C.UTF-8 \
	PYTHONUNBUFFERED=1 \
	PIP_DISABLE_PIP_VERSION_CHECK=1 \
	PIP_NO_CACHE_DIR=1 \
	UV_NO_CACHE=1

# OS packages: git + build tools (Python wheels without a 3.14 build), MariaDB client
# library/CLI (mysqlclient, backups), curl (healthcheck).
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		ca-certificates curl git build-essential pkg-config \
		libmariadb-dev mariadb-client libffi-dev libssl-dev \
		procps less xz-utils \
	&& rm -rf /var/lib/apt/lists/*

# Node 24 + yarn 1 from the official Node image (only needed to build Frappe's assets).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node /opt/ /opt/
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
	&& ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
	&& ln -s /opt/yarn-v*/bin/yarn /usr/local/bin/yarn \
	&& ln -s /opt/yarn-v*/bin/yarnpkg /usr/local/bin/yarnpkg \
	&& node --version && yarn --version

COPY deploy/tex-local/with-extra-ca.sh /usr/local/bin/with-extra-ca
RUN sed -i 's/\r$//' /usr/local/bin/with-extra-ca \
	&& chmod 0755 /usr/local/bin/with-extra-ca \
	&& groupadd --gid 1000 frappe \
	&& useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash frappe

# bench must not run as root
USER frappe
WORKDIR /home/frappe
ENV PATH=/home/frappe/.local/bin:${PATH}

RUN --mount=type=secret,id=extra_ca,required=false,uid=1000,mode=0444 \
	with-extra-ca python -m pip install --user --no-cache-dir "frappe-bench==${BENCH_VERSION}" \
	&& bench --version

RUN --mount=type=secret,id=extra_ca,required=false,uid=1000,mode=0444 \
	with-extra-ca bench init \
		--frappe-path "${FRAPPE_REPO}" --frappe-branch "${FRAPPE_BRANCH}" \
		--python /usr/local/bin/python3.14 \
		--skip-redis-config-generation --skip-assets --no-procfile --no-backups \
		frappe-bench \
	&& rm -rf /home/frappe/.cache

WORKDIR /home/frappe/frappe-bench

# payments' version-16 branch moves (develop declares Frappe v17); pin the commit this
# setup was verified with (a full commit SHA, tag or branch). PAYMENTS_REF= (empty) keeps
# the tip of PAYMENTS_BRANCH instead. Declared here, not at the top, so that changing it
# does not rebuild the layers above.
ARG PAYMENTS_REF=cca07d9f9392e2ea0e521c5975151db9e4b6c321

RUN --mount=type=secret,id=extra_ca,required=false,uid=1000,mode=0444 \
	with-extra-ca bench get-app --skip-assets --branch "${PAYMENTS_BRANCH}" "${PAYMENTS_REPO}" \
	&& if [ -n "${PAYMENTS_REF}" ] && [ "$(git -C apps/payments rev-parse HEAD)" != "${PAYMENTS_REF}" ]; then \
		with-extra-ca git -C apps/payments fetch --quiet --depth 1 "${PAYMENTS_REPO}" "${PAYMENTS_REF}" \
		&& git -C apps/payments checkout --quiet --detach FETCH_HEAD \
		&& with-extra-ca uv pip install --quiet --python env/bin/python -e apps/payments; \
	fi \
	&& echo "payments at $(git -C apps/payments rev-parse HEAD)" \
	&& rm -rf /home/frappe/.cache

# Frappe desk + payments assets. The sites/ directory becomes a named volume at run
# time, so the built assets live outside it (./assets) and sites/assets is a symlink
# that always points at the assets of the image in use.
RUN bench build --apps frappe,payments \
	&& mv sites/assets /home/frappe/frappe-bench/assets \
	&& ln -s /home/frappe/frappe-bench/assets sites/assets \
	&& rm -rf /home/frappe/.cache

# kamra's build backend, installed once here so that the kamra layer below (rebuilt on
# every code change) needs no network: kamra declares no Python dependencies of its own.
RUN --mount=type=secret,id=extra_ca,required=false,uid=1000,mode=0444 \
	with-extra-ca uv pip install --quiet --python env/bin/python "flit_core>=3.4,<4"

# The TEX app (Frappe app "kamra") from this repository. Its staff SPA (/kamra/tex) and
# guest booking engine (/book/<slug>) bundles are committed in kamra/public, so no
# npm build is needed.
COPY --chown=frappe:frappe . apps/kamra
RUN uv pip install --quiet --python env/bin/python --no-build-isolation -e apps/kamra \
	&& ln -sfn /home/frappe/frappe-bench/apps/kamra/kamra/public /home/frappe/frappe-bench/assets/kamra \
	&& printf 'frappe\npayments\nkamra\n' > sites/apps.txt \
	&& test -s apps/kamra/kamra/public/frontend/index.html \
	&& test -s apps/kamra/kamra/public/frontend/booking.html \
	&& env/bin/python -c "import frappe, payments, kamra; print('apps import OK')"

USER root
COPY deploy/tex-local/entrypoint.sh deploy/tex-local/Procfile deploy/tex-local/frappe_cli.py /opt/tex-local/
RUN sed -i 's/\r$//' /opt/tex-local/entrypoint.sh /opt/tex-local/Procfile /opt/tex-local/frappe_cli.py \
	&& chmod 0755 /opt/tex-local/entrypoint.sh \
	&& chmod 0644 /opt/tex-local/Procfile /opt/tex-local/frappe_cli.py
USER frappe

EXPOSE 8000
ENTRYPOINT ["/opt/tex-local/entrypoint.sh"]
