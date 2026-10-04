# TEX Engine — Development environment

## Versions (match upstream CI)
Frappe **v16.36.1**, Python **3.14**, Node **24**, MariaDB 10.11+/11.x, Redis, apps
`payments` (branch `version-16`) at commit `cca07d9` (CI's `PAYMENTS_REF`) + `kamra` (this repo). A bench made
before 2Z-F (Frappe v16.25.0, payments `develop`) moves in place as `deploy/tex-local/NATIVE.md` §5 shows.

## Cloud-session bench (reproducible recipe)
A fresh container has none of this (2O rebuilt it from scratch, about 20 minutes). Frappe v16.36.1 needs **Node 24**
(`bench init`'s `yarn install` refuses 22) and `cron` (`bench init` writes a crontab); CI uses MariaDB 11.8.
```bash
# system: MariaDB 11.8 from its own repository (Ubuntu 24.04 ships 10.11), Redis, cron, acl
curl -fsSL https://mariadb.org/mariadb_release_signing_key.pgp -o /etc/apt/keyrings/mariadb-keyring.pgp
echo "deb [signed-by=/etc/apt/keyrings/mariadb-keyring.pgp] https://mirror.mariadb.org/repo/11.8/ubuntu noble main" \
  > /etc/apt/sources.list.d/mariadb.list
apt-get update && apt-get install -y mariadb-server mariadb-client libmariadb-dev pkg-config redis-server cron acl
# /etc/mysql/mariadb.conf.d/99-frappe.cnf: utf8mb4, innodb_snapshot_isolation = OFF (ADR-063), then:
mysqld_safe &  ;  redis-server --daemonize yes --dir /tmp
mariadb -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('root')"
# python 3.14 (uv python install 3.14, linked as /opt/py314/bin/python3.14) and node 24 + yarn (/opt/node24)
# bench must not run as root; the checkout stays root's, the frappe user writes through an ACL:
useradd -m frappe
setfacl -R -m u:frappe:rwX -m d:u:frappe:rwX /home/user/TexEngine
# env.sh: PATH (node 24 first), the session's proxy, and every CA variable (SSL_CERT_FILE, REQUESTS_CA_BUNDLE,
# NODE_EXTRA_CA_CERTS, HTTPLIB2_CA_CERTS, …) at a copy of /root/.ccr/ca-bundle.crt the frappe user can read
su frappe; source /home/user/bench/env.sh
pip install frappe-bench==5.31.0          # CI's bench CLI (a venv of python 3.14)
bench init --skip-redis-config-generation --skip-assets --frappe-branch v16.36.1 \
  --python /opt/py314/bin/python3.14 frappe-bench
cd frappe-bench
bench set-config -g db_host 127.0.0.1 (+ redis_cache/queue/socketio)
git init -q apps/payments && git -C apps/payments fetch -q --depth 1 https://github.com/frappe/payments \
  cca07d9f9392e2ea0e521c5975151db9e4b6c321 && git -C apps/payments checkout -q FETCH_HEAD   # CI's PAYMENTS_REF
ln -s /home/user/TexEngine apps/kamra
uv pip install --python env/bin/python -e apps/payments -e apps/kamra
bench setup requirements --dev kamra     # freezegun: the scheduler smoke test (ADR-064)
printf "frappe\npayments\nkamra\n" > sites/apps.txt
bench new-site test.localhost --db-root-password root --admin-password admin
bench --site test.localhost install-app payments && bench --site test.localhost install-app kamra
bench --site test.localhost set-config developer_mode 1 && bench --site test.localhost set-config allow_tests true
bench --site test.localhost execute frappe.utils.password.get_encryption_key   # a new site has none yet (2O)
bench build --apps frappe,payments       # needed by email-rendering tests
```
Without the `encryption_key`, six `test_member_web` tests fail when the module runs alone on a new site (CI's run
makes the key earlier, in the eval harness).
Notes: Python 3.14's strict X.509 verification rejects the session proxy CA for
`api.github.com` in `bench get-app`, hence the manual `git clone`.

## Running tests
```bash
# pure pricing/unit tests (no bench needed)
python3 -m pytest kamra/tex/tests/unit -q
# upstream suites
/home/user/bench/run_baseline.sh /home/user/bench/<outdir>
# TEX integration tests
bench --site test.localhost run-tests --module kamra.tex.tests.integration.test_<name>
# frontend
cd frontend && npm ci && npm run build
```

**Tests that change the whole site** (`test_patches`: an empty site, every patch over the site, the
Kamra upgrade; ADR-058 review) run only on a disposable site, whose site config sets
`tex_disposable_test_site`. On a shared site they are skipped: even rolled back, they hold locks
that other sessions wait on. Make one for the run and drop it after:
```bash
bench new-site texmig.localhost --db-root-password root --admin-password admin \
  --install-app payments --install-app kamra
bench --site texmig.localhost set-config allow_tests true
bench --site texmig.localhost set-config -p tex_disposable_test_site 1
bench --site texmig.localhost run-tests --module kamra.tex.tests.integration.test_patches
bench drop-site texmig.localhost --db-root-password root --force --no-backup
```
On the cloud-session bench, `/home/user/bench/scratch/disposable_test.sh <tree> <outdir> [modules]`
does all of this under the bench-test lock (about 40 s to make the site). Every migration test also
refuses commits until it rolled back, so a run stopped with Ctrl-C commits nothing.

## Demo data and browser E2E
```bash
# demo enterprise, hotels, contracts, users (revenue@, agent@, finance@, beach.gm@demo.tex)
bench --site test.localhost execute kamra.tex.devtools.demo_seed.execute --kwargs "{'password': 'TexDemo#2026'}"
# the public booking API is rate limited per IP; raise it on test benches only
bench --site test.localhost set-config -p tex_public_write_limit 1000
bench --site test.localhost set-config -p tex_public_search_limit 1000
bench serve --port 8000        # test.localhost must resolve to 127.0.0.1
# a paid guest change and a refund are made by a job: a worker runs them (CI does the same; the site's scheduler stays
# off). Without it manage-money.spec's two paid changes wait for nothing (2O's full run lost them this way)
bench worker --queue short,default &
bench schedule &
cd frontend && TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD='TexDemo#2026' \
  PW_CHROMIUM=/opt/pw-browsers/chromium npx playwright test -c e2e
```
Stop the worker and the scheduler again (`pkill -f "bench worker"`, `pkill -f "bench schedule"`) before the next
integration run: left running, they take the test site's jobs while the tests run (2P).
Repeated runs book real inventory at the demo hotels; free it between series of runs with
`bench --site test.localhost execute kamra.tex.devtools.demo_seed.release_test_bookings`
(cancels future test-run stays, keeps demo-seed bookings; refuses on production sites).
CI starts from a fresh database each run.

Specs: the 52 `*.spec.ts` files in `frontend/e2e/` (CI runs them all), among them `shell`,
`contract-admin`, `booking` (desktop + 390 px), `crs` (call centre, reservation change) and
`critical-journey` (R-58, 19 steps). Reusable steps live in `e2e/flows/`
(contracts, booking, reservations) and `e2e/helpers.ts`. The dev bench's System Settings
time zone is Europe/Istanbul (the demo hotels are in Türkiye).

## Local testing on your own machine
For sales/revenue staff and developers who want TEX Engine with the demo data on a laptop
(macOS, Windows 10/11, Linux), see [`deploy/tex-local/README.md`](../../deploy/tex-local/README.md):
Docker Compose (`cd deploy/tex-local && docker compose up -d`, then
`http://localhost:8000/kamra/tex`) or, without Docker, a native bench made by
`deploy/tex-local/setup-local.sh` ([`NATIVE.md`](../../deploy/tex-local/NATIVE.md)). Both are
for local testing only (well-known demo passwords, `developer_mode`, never `tex_production`).

## After a container restart
Cloud containers can restart between turns; files survive, processes do not (and the proxy's port and CA may
change: refresh the CA copy `env.sh` points at, `cp /root/.ccr/ca-bundle.crt /home/user/bench/`). Bring the
services back (as root):
```bash
mysqld_safe > /dev/null 2>&1 &                     # MariaDB (root password "root")
redis-server --daemonize yes --dir /tmp            # Redis 6379 (keep its dump out of the repo)
grep -q test.localhost /etc/hosts || echo "127.0.0.1 test.localhost" >> /etc/hosts   # Node/Playwright need it
su frappe -s /bin/bash -c "source /home/user/bench/env.sh; cd /home/user/bench/frappe-bench; \
  nohup bench serve --port 8000 >> /home/user/bench/serve.log 2>&1 &"
```
`env.sh` takes the proxy from the session's `HTTPS_PROXY` (its port changes on restart). Bench
test runs shared by several agents go through `/home/user/bench/scratch/benchtest.sh <tree> <module>`
(one run at a time, under a file lock).
