# TEX Engine — Development environment

## Versions (match upstream CI)
Frappe **v16.25.0**, Python **3.14**, Node **24**, MariaDB 10.11+/11.x, Redis, apps
`payments` (develop) + `kamra` (this repo).

## Cloud-session bench (reproducible recipe)
```bash
# system
apt-get update && apt-get install -y mariadb-server mariadb-client libmariadb-dev pkg-config redis-server
# utf8mb4 config in /etc/mysql/mariadb.conf.d/99-frappe.cnf, then:
mysqld_safe &  ;  redis-server --daemonize yes
mysql -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('root')"
# python 3.14 + node 24 (+ yarn) ; bench must not run as root:
useradd -m frappe
su frappe; source /home/user/bench/env.sh     # PATH, proxy CA vars
bench init --skip-redis-config-generation --skip-assets --frappe-branch v16.25.0 \
  --python /opt/py314/bin/python3.14 frappe-bench
cd frappe-bench
bench set-config -g db_host 127.0.0.1 (+ redis_cache/queue/socketio)
git clone --depth 1 -b develop https://github.com/frappe/payments apps/payments
ln -s /home/user/TexEngine apps/kamra
uv pip install --python env/bin/python -e apps/payments -e apps/kamra
printf "frappe\npayments\nkamra\n" > sites/apps.txt
bench new-site test.localhost --db-root-password root --admin-password admin
bench --site test.localhost install-app payments && bench --site test.localhost install-app kamra
bench --site test.localhost set-config developer_mode 1 && bench --site test.localhost set-config allow_tests true
bench build --apps frappe,payments       # needed by email-rendering tests
```
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
