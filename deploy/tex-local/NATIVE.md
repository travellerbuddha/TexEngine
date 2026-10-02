# TEX Engine on your own computer, without Docker

This guide sets up a full TEX Engine on a laptop or dev machine: the staff app, the guest
booking engine and Frappe Desk, with demo hotels, contracts and users. It runs directly on
macOS, Linux or Windows (through WSL2), without Docker.

> **Local testing only.** The default passwords (`admin`, `TexDemo#2026`) are public. Keep
> real guest, card or company data off this bench. By default it only accepts connections
> from your own computer.

```bash
git clone <TEX Engine repository URL> tex-engine
cd tex-engine
deploy/tex-local/setup-local.sh        # asks for your MariaDB root password
cd ../tex-bench && bench start         # then open http://localhost:8000/kamra/tex
```

The bench is created next to the checkout (`../tex-bench`), never inside it.

The first run downloads Frappe, about 200 Python packages and about 1,000 npm packages, then
builds Frappe's assets. Most of the time goes to downloads. On a machine that already had
those packages cached, it took 81 seconds. On a fresh laptop, expect 10–20 minutes (an
estimate, not measured). A later run skips everything that is already done and takes a few
seconds.

---

## 1. Prerequisites

| What | Version | Why |
| --- | --- | --- |
| Python | **3.14** | Frappe v16 needs exactly 3.14. [uv](https://docs.astral.sh/uv/) can install it for your user only. |
| uv | recent | `bench` runs it to install Python packages |
| Node.js + Yarn | **Node 24**, **Yarn 1** (classic) | Frappe's realtime server and asset build |
| git | any recent | fetches Frappe and payments |
| MariaDB server + client | 10.6–11.8 (11.8 recommended) | the database. You need its **root password**. The script warns about other versions. |
| Redis | 6 or newer | only the `redis-server` program is needed. The bench starts its own private copies. The system Redis service can stay off. |
| C compiler, pkg-config, MariaDB client headers | – | only for the first run, to build the `mysqlclient` Python package |
| Disk / RAM | ~3 GB / 4 GB free | |

The script also needs the `bench` command (`frappe-bench`). If it is missing, the script
offers to install it with `uv tool install frappe-bench`. It does the same for Python 3.14
with `uv python install 3.14`. Both installs are for your user only, and the script asks
before each one unless you pass `--yes`. The script never runs `sudo`. When something is
missing, it prints the install command for you to run.

### macOS (Apple Silicon and Intel)

```bash
xcode-select --install                     # compiler + git (skip if already installed)
brew install uv redis mariadb@11.8 mariadb-connector-c pkgconf node@24
# mariadb@11.8 and node@24 are keg-only: put them on PATH
echo 'export PATH="$(brew --prefix mariadb@11.8)/bin:$(brew --prefix node@24)/bin:$PATH"' >> ~/.zprofile
exec zsh -l                                # reload the shell so mariadb and node are on PATH
npm install -g yarn
uv python install 3.14
brew services start mariadb@11.8
```

Install `mariadb@11.8`, not plain `mariadb`: Homebrew's `mariadb` formula is MariaDB 13
(13.0.2 in September 2026), which TEX has not been tested with. 11.8 is the long-term
release the Docker setup uses. `mariadb-connector-c` and `pkgconf` are needed to build
Python's MariaDB driver; `bench` looks for `mariadb-connector-c` by name on macOS. If you
already use `nvm`, then `nvm install 24` works instead of `node@24`. (These macOS steps
have not been run on a Mac yet.)

**MariaDB root password.** A fresh Homebrew MariaDB lets `root` log in only through
`sudo`. Give root a password and keep the `sudo` login:

```bash
sudo mariadb -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket OR mysql_native_password USING PASSWORD('choose-a-local-password');"
```

### Ubuntu / Debian (and Windows through WSL2)

```bash
sudo apt update
sudo apt install -y git curl build-essential pkg-config libmariadb-dev \
                    mariadb-server mariadb-client redis-server
curl -LsSf https://astral.sh/uv/install.sh | sh          # then open a new terminal
uv python install 3.14
# Node 24 + Yarn 1 through nvm (no sudo needed)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash   # then open a new terminal
nvm install 24
npm install -g yarn
```

Installing `redis-server` also starts a system Redis on port 6379. This bench does not use
that one. If you have no other use for it, `sudo systemctl disable --now redis-server` turns
it off.

**MariaDB root password.** On Debian and Ubuntu, `root` logs in through `sudo` only. Give
it a password and keep the `sudo` login:

```bash
sudo mariadb -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket OR mysql_native_password USING PASSWORD('choose-a-local-password');"
```

### Windows 10 / 11: use WSL2

Frappe does not run natively on Windows, so run everything inside Ubuntu on WSL2.

1. Open PowerShell **as Administrator** and run `wsl --install -d Ubuntu-24.04`. Restart
   when it asks, then open "Ubuntu" from the Start menu and create your Linux user.
2. Inside Ubuntu, follow the Ubuntu steps above.
3. Clone the repository **inside the Linux home** (`cd ~ && git clone …`). Do not clone it
   under `/mnt/c/...`: the Windows drive is very slow from WSL and the setup takes much longer.
4. If WSL runs without systemd, services do not start by themselves. Start MariaDB with
   `sudo service mariadb start` after each Windows restart, or turn on systemd: put
   `[boot]` and `systemd=true` in `/etc/wsl.conf`, then run `wsl --shutdown` from PowerShell.
5. Open `http://localhost:8000/...` in your Windows browser. WSL forwards `localhost` to
   Linux. If the page does not load, see [Troubleshooting](#7-troubleshooting).

### MariaDB character set and snapshot isolation (all systems)

Frappe needs `utf8mb4`. TEX needs `innodb_snapshot_isolation` off: MariaDB 11.6.2 and later
turn it on by default, and then a booking that waited for the last room gets an error instead
of "sold out" (ADR-063). The `loose-` prefix lets an older MariaDB without the setting start
anyway. Add this file, then restart MariaDB:

```ini
[mysqld]
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
loose-innodb_snapshot_isolation = 0

[mysql]
default-character-set = utf8mb4
```

| System | File | Restart |
| --- | --- | --- |
| Ubuntu / Debian / WSL2 | `/etc/mysql/mariadb.conf.d/99-tex.cnf` | `sudo systemctl restart mariadb` (WSL without systemd: `sudo service mariadb restart`) |
| macOS (Homebrew) | `$(brew --prefix)/etc/my.cnf.d/tex.cnf` | `brew services restart mariadb@11.8` |

To check: `mariadb -uroot -p -e "SELECT @@character_set_server, @@collation_server"` should
print `utf8mb4  utf8mb4_unicode_ci`, and `mariadb -uroot -p -e "SELECT @@GLOBAL.innodb_snapshot_isolation"`
should print `0` (MariaDB before 10.6.18 has no such setting: an error there is fine). The setup
script prints a warning when either is not so.

---

## 2. Run the setup

From your checkout:

```bash
deploy/tex-local/setup-local.sh
```

The bench is created next to your checkout: for a checkout in `~/tex-engine` it is
`~/tex-bench`. The script refuses a `--dir` inside the checkout, because git and the Docker
build would then pick up the bench's Python environment, passwords, encryption keys and
backups. Nothing is installed system-wide. Your checkout is linked into the bench, not
copied, so code you edit or pull is what the bench runs.

| Option | Default | Meaning |
| --- | --- | --- |
| `--dir DIR` | `tex-bench` next to the checkout | bench directory (no spaces in the path, not inside the checkout). A bench this script did not create is refused unless you add `--adopt`. |
| `--site NAME` | `tex.localhost` | site name |
| `--port N` | `8000` | web port. It also moves the realtime port (N+1000) and the private Redis ports (N+3000, N+5000). |
| `--db-root-password PW` | asked | MariaDB root password. Needed only when a site is created or reset. |
| `--admin-password PW` | `admin` | password of the site's `Administrator` |
| `--demo-password PW` | `TexDemo#2026` | password of the demo users |
| `--repo PATH` | this checkout | the TEX Engine checkout to link in as the `kamra` app |
| `--python PATH` | auto | the Python 3.14 to use |
| `--db-host HOST`, `--db-port N` | `127.0.0.1`, `3306` | MariaDB location (for example MariaDB running in Docker) |
| `--redis bench\|URL` | `bench` | `bench`: private Redis servers on 127.0.0.1, which `bench start` runs. With a URL such as `redis://127.0.0.1:6379/2`, the bench uses a Redis you already run instead. Give it a Redis or database number of its own, because rebuilding assets flushes it. |
| `--bind ADDR` | `127.0.0.1` | address the web and realtime servers listen on. `0.0.0.0` makes them reachable from your network (see §3). |
| `--time-zone TZ` | `Europe/Istanbul` | time zone of the site and the demo hotels. Applied only when the demo data is loaded (see "Time zone"). |
| `--adopt` | – | allow `--dir` to name an existing bench that this script did not create. The script then rewrites that bench's ports, Redis settings, `Procfile` and default site, which affects all of its sites. |
| `--reset` | – | drop the site (a backup is kept under `tex-bench/archived/sites/`) and create it again with fresh demo data |
| `--yes`, `-y` | – | answer yes to questions (installing bench or Python, confirming `--reset`) |

Every option can also be set as an environment variable: `TEX_DIR`, `TEX_SITE`,
`TEX_PORT`, `TEX_DB_ROOT_PASSWORD`, `TEX_ADMIN_PASSWORD`, `TEX_DEMO_PASSWORD`, `TEX_REPO`,
`TEX_PYTHON`, `TEX_DB_HOST`, `TEX_DB_PORT`, `TEX_REDIS`, `TEX_BIND`, `TEX_TIME_ZONE`. A few
more exist only as environment variables: `TEX_FRAPPE_BRANCH` (`v16.25.0`),
`TEX_PAYMENTS_URL`, `TEX_PAYMENTS_BRANCH` (`develop`) and `TEX_PAYMENTS_REF` (the verified
payments commit `86fefa9faf8ad825fe6f08c4753acfe44817900b`; set it empty to use the tip of
`TEX_PAYMENTS_BRANCH`, not verified).

Examples:

```bash
deploy/tex-local/setup-local.sh --dir ~/tex-bench --port 8010
TEX_DB_ROOT_PASSWORD=secret deploy/tex-local/setup-local.sh --yes      # no questions
deploy/tex-local/setup-local.sh --redis redis://127.0.0.1:6379/2        # use your own Redis
```

### What the script does

1. **Checks prerequisites.** It lists everything that is missing in one go, with the
   install command for your system. It also logs in to MariaDB as root, warns if the
   character set is wrong, and warns about MariaDB versions outside 10.6–11.8. It refuses
   an existing bench it did not create (unless `--adopt`) and any bench with a site
   flagged `tex_production`, before it changes anything.
2. **Creates the bench**: `bench init --frappe-branch v16.25.0 --python <3.14>
   --no-backups --skip-assets`. `--no-backups` means no crontab entry is added.
3. **Writes the configuration.** Ports and Redis settings go into
   `sites/common_site_config.json`. It also writes a `Procfile` and two small wrappers in
   `tex-bench/tex-local/` that make the web and realtime servers listen on `--bind`. Frappe's
   own `bench serve` always listens on all network interfaces, with the Werkzeug debugger on.
4. **Gets payments**: `bench get-app --branch develop https://github.com/frappe/payments`,
   then checks out the verified commit `86fefa9` (payments' `develop` moves, and already
   declares Frappe v17 as its target). It uses the full URL on purpose: short app names
   make bench call the GitHub API.
5. **Links your checkout** as `apps/kamra` (a symlink) and installs it in the bench's
   Python in editable mode.
6. **Starts the bench's private Redis** for the next steps and stops it again at the end.
7. **Creates the site**: `bench new-site`. It is never dropped unless you pass `--reset`.
   The MariaDB root and Administrator passwords are not put on bench's command line:
   `bench` writes every command line to `logs/bench.log`, so `new-site` and `drop-site`
   run through `deploy/tex-local/frappe_cli.py`, which takes them from the environment.
8. **Installs** `payments` and `kamra` on the site.
9. **Migrates** the site on a re-run (`bench --site <site> migrate`), so new DocTypes and
   patches from a `git pull` are applied. Skipped when the site was just created.
10. **Applies site settings.** It turns on `developer_mode` and `allow_tests`, and raises
    the public booking API rate limits (`tex_public_search_limit` and
    `tex_public_write_limit`) to 1000, which suits a test bench only. It makes sure the
    site has an `encryption_key`: TEX signs offer keys and payment links with it and has
    no fallback, but a new Frappe site only gets one later, the first time Frappe needs
    it. It then runs `bench use <site>` and enables the scheduler.
11. **Loads the demo data** (`kamra.tex.devtools.demo_seed`) with the site and the demo
    hotels on `--time-zone` (Europe/Istanbul). This runs only once: a re-run does not seed
    again. See "Time zone" below.
12. **Builds assets**: `bench build --apps frappe,payments`. The TEX staff app and booking
    engine bundles are already committed in `kamra/public`, so there is no npm build for
    TEX. Never run a plain `bench build` here. It would run kamra's npm build and rewrite
    those committed bundles.

At the end it prints the time each step took, the URLs, the logins and how to start the bench.

### Time zone

The site and both demo hotels run on **Europe/Istanbul** (or `--time-zone`), the same as
the Docker setup and the shared dev bench. The staff app shows times in the site's zone.

The zone has to be right *before* the demo data is loaded, and the script does it in
this order:

1. It sets the site's time zone (System Settings).
2. While the demo data is loaded, it makes the zone the default for new hotels (a
   temporary Property Setter on the hotel's `timezone` field). Without it the demo hotels
   would get Kamra's default, Asia/Kolkata, and saving the first hotel of a site copies its
   zone into System Settings.
3. It loads the demo data, removes the Property Setter and sets the site's zone once more.

Do not change the site's time zone afterwards. Frappe stores times without a zone, so a
change moves "now" but not the stored times. The contracts are published during setup in
the site's local time. After a switch to a zone further west (for example Europe/Berlin),
they count as not yet effective for the hours of difference, and the booking engine finds
no offers. If that happened, switch back, or start over with `--reset --time-zone <zone>`.
Frappe Desk's setup wizard (Administrator, `/desk`) also asks for a time zone: keep
Europe/Istanbul there.

### What it changes on your computer

It creates the bench directory, one MariaDB database and one MariaDB user for the site.
If you say yes, it also installs `bench` and Python 3.14 for your user. It does **not** run
`sudo`, change system services, add crontab entries, or write files in your checkout. The
asset links only point into `kamra/public`.

---

## 3. Start and stop

```bash
cd tex-bench
bench start          # Ctrl+C stops everything
```

`bench start` runs the processes in the `Procfile`: the two private Redis servers (not
with `--redis URL`), the web server, the realtime server, the scheduler and two background
workers (`short,default`, and `long` for the PMS outbox; System status names a queue no
worker listens on). Nothing runs
between sessions, so start it again after a restart.

| Open | URL (default port 8000) |
| --- | --- |
| TEX staff app | http://localhost:8000/kamra/tex |
| Guest booking engine | http://localhost:8000/book/aurora |
| Frappe Desk (admin) | http://localhost:8000/desk |

The site is the bench's default site, so any host name on that port reaches it. That
includes `http://tex.localhost:8000`, which browsers resolve to your own computer.

| Login | Password | Role |
| --- | --- | --- |
| `Administrator` | `admin` | everything (Desk) |
| `revenue@demo.tex` | `TexDemo#2026` | revenue manager, whole hotel group |
| `agent@demo.tex` | `TexDemo#2026` | call-centre / reservations agent |
| `finance@demo.tex` | `TexDemo#2026` | finance |
| `beach.gm@demo.tex` | `TexDemo#2026` | hotel admin, Aurora Beach Resort only |

The demo also has a promotion code `EARLY10`, a Sandbox card gateway, a bank transfer
option and a few bookings.

**In the background** (for example on a machine you connect to over SSH):

```bash
cd tex-bench
nohup bench start > logs/bench-start.log 2>&1 &
echo $! > tex-local/bench-start.pid
# later, to stop it:
kill $(cat tex-local/bench-start.pid)
```

**From a phone or another computer.** Re-run the script with `--bind 0.0.0.0`, restart
`bench start`, and open `http://<your computer's IP>:8000/book/aurora`. Change the
passwords first, because anyone on that network can reach the login page. To make it
local-only again, re-run with `--bind 127.0.0.1`.

---

## 4. Start over or remove it

* **Fresh demo data:** `deploy/tex-local/setup-local.sh --reset` (the same `--dir` if you
  changed it). The site is dropped, with a backup under `tex-bench/archived/sites/`, then
  created and seeded again.
* **Free the demo rooms that test bookings used up:**
  `bench --site tex.localhost execute kamra.tex.devtools.demo_seed.release_test_bookings`
* **Remove everything:** stop `bench start`, then:
  ```bash
  cd tex-bench && bench drop-site tex.localhost --force   # asks for the MariaDB root password
  cd .. && rm -rf tex-bench
  ```
  Your checkout is not affected, because `apps/kamra` is only a link to it.

---

## 5. Update to newer code

```bash
cd tex-engine && git pull                     # your checkout, linked into the bench
cd ../tex-bench                               # wherever your bench is
bench --site tex.localhost migrate            # apply new DocTypes and patches
# then restart: Ctrl+C in the `bench start` terminal, and `bench start` again
```

You do not need to build anything for TEX: the staff app and booking engine bundles come
with the code. Instead of `bench migrate` you can re-run `setup-local.sh` (with the same
`--dir` if you changed it): it migrates the site and completes anything that is missing.

* **payments** is pinned to a verified commit (a detached checkout, so `git pull` does not
  work there). To move it, for example to payments' Frappe v16 branch (not verified with
  TEX): `cd apps/payments && git fetch --depth 1 https://github.com/frappe/payments version-16 && git checkout --detach FETCH_HEAD && cd ../.. && bench --site tex.localhost migrate && bench build --apps frappe,payments`
* **A different Frappe version:** the simplest way is a new bench next to the old one, for
  example `TEX_FRAPPE_BRANCH=v16.26.0 deploy/tex-local/setup-local.sh --dir ~/tex-bench-new`.
  Then remove the old one (§4).
* **After a Frappe or payments update:** `bench build --apps frappe,payments`

**For developers:**

* The web server reloads by itself when Python files change. Restart `bench start` to
  reload the worker and the scheduler.
* Developer mode is on, so saving a DocType in Desk writes its JSON into your checkout.
  That is how TEX DocTypes are changed. Commit those files like any other code.
* Tests on this bench: `bench --site tex.localhost run-tests --module kamra.tex.tests.integration.<module>`.
  Pure pricing tests need no bench: `python -m pytest kamra/tex/tests/unit -q`.
* Live frontend development (not tested with this setup): `cd frontend && npm install && npm run dev`
  serves the SPA on :5173 and proxies `/api` to `http://localhost:8000`.
* E2E with Playwright (not tested with this setup), from `frontend/`: run
  `npx playwright install chromium` once, then
  `TEX_E2E_BASE=http://tex.localhost:8000 TEX_E2E_PASSWORD='TexDemo#2026' npx playwright test -c e2e`

---

## 6. Behind a company proxy

Nothing about proxies is stored in the bench or the script. If your network needs a proxy
or inspects TLS with its own certificate authority, export the usual variables in the
terminal before you run the script. `bench start` picks them up the same way.

```bash
export HTTPS_PROXY=http://proxy.example:3128
export SSL_CERT_FILE=/path/to/company-ca.pem REQUESTS_CA_BUNDLE=$SSL_CERT_FILE \
       NODE_EXTRA_CA_CERTS=$SSL_CERT_FILE GIT_SSL_CAINFO=$SSL_CERT_FILE
```

Python 3.14 checks certificates more strictly and rejects some TLS-inspection CAs. The
setup only downloads through git, uv and yarn, never through Python's own HTTPS, so this
does not block it.

---

## 7. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Python 3.14 not found` | `uv python install 3.14`, or pass `--python /path/to/python3.14` |
| `Access denied for user 'root'` | give root a password (§1, "MariaDB root password") and pass it with `--db-root-password` |
| `Can't connect to server on '127.0.0.1'` | MariaDB is not running: `brew services start mariadb@11.8` or `sudo service mariadb start` |
| building `mysqlclient` fails (`pkg-config`, `mysql_config`, `mariadb_config`) | macOS: `brew install mariadb-connector-c pkgconf`. Debian/Ubuntu: `sudo apt install libmariadb-dev pkg-config build-essential`. Then re-run. |
| `… exists but is not a complete bench` | an earlier first run failed half-way. Remove that directory and re-run. |
| `… is inside the TEX Engine checkout` | choose a `--dir` outside the checkout; the default (`tex-bench` next to it) is fine |
| `… is an existing Frappe bench that this script did not create` | choose a new `--dir`. Only if you really want this bench reconfigured for TEX, add `--adopt`. |
| `MariaDB 13.… is outside the versions …` | a warning only. If something fails, install MariaDB 11.8 (macOS: `brew install mariadb@11.8`, see §1) |
| `port … is already in use` | another program (or another bench) uses it. Pick another `--port`; the other ports move with it. |
| `bench start`: `Address already in use` | another `bench start` is still running, perhaps in another terminal, or a different bench uses the same ports. Stop it, or re-run the setup with another `--port`. |
| `bench: command not found` after setup | `uv tool update-shell`, then open a new terminal |
| a page has no styles, or `/assets/...` returns 404 | `bench build --apps frappe,payments` (never a plain `bench build`, see §2 step 11) |
| `http://tex.localhost:8000` does not open | some tools do not resolve `*.localhost`. Use `http://localhost:8000`, which serves the same site. |
| booking engine finds no rooms and the log says "No contract sells this hotel" | if you changed the site's time zone after the demo data was loaded (in Desk or the setup wizard), contracts published at setup are "in the future" for a few hours (see §2, "Time zone"). Change the time zone back or run `--reset`. |
| booking engine says "too many requests" | check that `tex_public_search_limit` and `tex_public_write_limit` are in `sites/<site>/site_config.json` (re-run the script) |
| demo users cannot log in | `bench --site tex.localhost execute kamra.tex.devtools.demo_seed.execute --kwargs "{'password': 'TexDemo#2026'}"` (idempotent, resets their passwords) |
| Windows browser cannot reach the WSL bench | check `curl http://localhost:8000/api/method/ping` inside Ubuntu first. If that works, turn on WSL "mirrored" networking (`networkingMode=mirrored` under `[wsl2]` in `%UserProfile%\.wslconfig`, then `wsl --shutdown`), or re-run with `--bind 0.0.0.0` |
| macOS: worker crashes with `objc … fork()` | the generated `Procfile` already sets `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`. Re-run the script if you replaced the Procfile. |
| after `bench setup procfile` the servers listen on all interfaces | that command writes Frappe's default Procfile. Re-run `setup-local.sh` to restore the local-only one. |
| where are the logs? | the terminal running `bench start`, plus `tex-bench/logs/` (`worker.error.log`, `frappe.log`, …) |

The realtime server prints `listening on: ws://0.0.0.0:9000` even when it only listens on
127.0.0.1. That text is hard-coded in Frappe; the socket really is bound to `--bind`.

---

## Tested on

Ubuntu 24.04 (x86_64) with MariaDB 10.11.14, Redis 7.0.15, Python 3.14.7, Node 24.21.0,
Yarn 1.22.22 and bench 5.31.0, on 2026-09-23, with warm package caches.

* First run: 87 s (81 s in an earlier version). A re-run while `bench start` was running:
  11 s, of which the migrate took 7 s, with nothing seeded again.
* Site and both demo hotels on Europe/Istanbul, the temporary Property Setter removed,
  the booking engine returning offers.
* `logs/bench.log` holds none of the passwords (MariaDB root, Administrator, demo users).
* `bench start` in the background, and stopping it through the pid file.
* Checks: `ping`, the demo logins, `/kamra/tex`, `/book/aurora` and `/desk` with their
  bundles, a public search (30 priced offers), a quote from a signed offer key, scheduled
  jobs run by the worker, and the Playwright specs `shell`, `booking` and `crs`
  (desktop, 7 passed).
* All servers listen on 127.0.0.1 only. `--bind 0.0.0.0`, `--redis URL`, `--reset` and
  the error messages for missing prerequisites were checked too, as were the refusals
  (a `--dir` inside the checkout, a bench the script did not create, a `tex_production`
  site) and the recovery with `--reset` after a `new-site` that crashed half-way.

The macOS and Windows/WSL2 steps have not been run yet. If one of them differs on your
machine, please correct this guide.
