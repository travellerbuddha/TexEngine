# TEX Engine on your computer with Docker (local testing)

> **For local testing only.** This stack runs TEX Engine with demo data, well-known default
> passwords, Frappe's `developer_mode` and a development web server. It listens on your
> own computer only (`127.0.0.1`). Never put real guest or card data into it, and never
> expose it to a network or the internet.

## Hızlı başlangıç (Türkçe)

Otel satış / gelir ekipleri için, yazılım bilgisi gerekmez:

1. **Docker Desktop'ı kurun ve açın** (Windows 10/11 ve macOS: <https://www.docker.com/products/docker-desktop/>;
   Linux'ta Docker Engine + Compose eklentisi). Diskte **~10 GB boş yer** gerekir. Bellek:
   Docker'a en az **2 GB**, tercihen **4 GB** kalsın. macOS'ta bu ayar Docker Desktop'ta
   *Settings → Resources → Memory* altındadır. Windows'ta (WSL 2) böyle bir ayar yoktur:
   Docker bilgisayarın belleğinin yarısını kullanabilir, 8 GB ve üzeri bellekli bir
   bilgisayarda bir şey yapmanız gerekmez.
   *Lisans:* Docker Desktop kişisel kullanımda ve küçük şirketlerde ücretsizdir; 250'den
   fazla çalışanı **veya** 10 milyon ABD dolarından fazla yıllık geliri olan şirketlerde
   ücretli abonelik ister (otel grupları için şirketinizin BT birimine sorun). Linux'taki
   Docker Engine ücretsizdir; Docker'sız kurulum için [NATIVE.md](NATIVE.md).
2. **Kodu indirin.** Git biliyorsanız:
   `git clone https://github.com/travellerbuddha/TexEngine.git`
   Bilmiyorsanız: <https://github.com/travellerbuddha/TexEngine> sayfasında
   **Code → Download ZIP** ile indirip açın (depo özelse önce GitHub hesabınızla giriş
   yapın). İkisi de deponun varsayılan dalını indirir.
3. **Terminali açın** (Windows: PowerShell, macOS: Terminal), indirdiğiniz klasöre geçip
   şunu çalıştırın:
   ```
   cd TexEngine/deploy/tex-local
   docker compose up -d
   ```
   (ZIP ile indirdiyseniz klasörün adı `TexEngine-` ile başlar, ardından dalın adı gelir.)
4. **İlk açılışı bekleyin.** İlk seferde Docker önce programı derler, sonra veritabanını
   kurup demo verisini yükler. Ölçülen süre: derleme ~6,5 dk + ilk kurulum ~1,5 dk; kendi
   internet hızınıza göre **10–20 dakika** ayırın. Hazır olunca `docker compose ps`
   komutunda `tex` satırında **healthy** yazar. İlerlemeyi izlemek için
   `docker compose logs -f tex` (Ctrl+C ile izlemeyi bırakırsınız, sistem çalışmaya devam eder).
   Sonraki açılışlar ~30 saniye sürer.
5. **Tarayıcıda açın:**
   * Personel uygulaması (CRS, rezervasyonlar, fiyat & kontratlar): <http://localhost:8000/kamra/tex>
   * Misafir rezervasyon motoru: <http://localhost:8000/book/aurora>
   * Kullanıcılar (şifre: `TexDemo#2026`):
     `revenue@demo.tex` (gelir müdürü), `agent@demo.tex` (çağrı merkezi),
     `finance@demo.tex` (finans), `beach.gm@demo.tex` (yalnız Aurora Beach Resort).

**Bu ortamda gerçek olan hiçbir şey yok:** kart ödemeleri "Sandbox payment page" adlı
test sayfasına gider (gerçek kart istenmez, "Simulate successful / declined payment"
düğmeleriyle sonuç seçilir); **e-posta gönderilmez**; kanal (channel manager) bağlantıları
*Sandbox*'tır, dışarıya hiçbir şey göndermez. Şifreler herkesçe bilinen test şifreleridir.

Durdurmak: `docker compose stop` · Tekrar başlatmak: `docker compose up -d` ·
Her şeyi silip sıfırdan başlamak: `docker compose down -v` ve ardından `docker compose up -d`.

**Port 8000 doluysa** (hata: `port is already allocated`), `deploy/tex-local` klasöründe
şu komutla bir `.env` dosyası oluşturun, sonra `docker compose up -d` komutunu tekrar
çalıştırın ve <http://localhost:8010/kamra/tex> adresini açın:
* Windows PowerShell: `Set-Content .env 'TEX_PORT=8010' -Encoding ascii`
* macOS / Linux: `echo 'TEX_PORT=8010' > .env`

Diğer ayarlar için: Windows'ta `Copy-Item .env.example .env; notepad .env`, macOS/Linux'ta
`cp .env.example .env` ve bir metin düzenleyici. Windows PowerShell'de `.env` dosyasını
`echo ... > .env` ile **oluşturmayın**: dosya UTF-16 olarak yazılır ve hiçbir
`docker compose` komutu çalışmaz.

Derleme sertifika (TLS / certificate) hatasıyla duruyorsa şirket ağınız HTTPS'i kendi
sertifikasıyla yeniden imzalıyor olabilir: aşağıdaki *The build fails while downloading*
bölümüne bakın (BT biriminizden şirketin kök sertifikasını isteyin).

---

## What you get

| Service | Image | Purpose |
| --- | --- | --- |
| `db` | `mariadb:11.8` (utf8mb4) | database, named volume `tex-local_db-data` |
| `redis` | `redis:7-alpine` | cache and background-job queue (no persistence) |
| `tex` | built from this repository (`Dockerfile`) | Frappe v16.36.1 + `payments` (version-16, pinned to commit `cca07d9`) + `kamra` (TEX Engine): web server, scheduler and two background workers (`short,default` and `long`, where the PMS outbox runs) |

The `tex` image is Python 3.14 (Debian bookworm) with Node 24 + Yarn 1, a non-root user
`frappe`, a bench made with `bench init --frappe-branch v16.36.1`, the `payments` app from
`https://github.com/frappe/payments` (branch `version-16`, pinned to the verified commit
`cca07d9f9392…`), and the `kamra` app copied from this repository and installed editable.
The TEX staff app and guest booking engine bundles are committed in `kamra/public`, so
there is no npm build for TEX; only Frappe's own assets are built
(`bench build --apps frappe,payments`).

### URLs and logins (default port 8000)

| What | URL | Login |
| --- | --- | --- |
| TEX staff app | <http://localhost:8000/kamra/tex> (also <http://localhost:8000/>) | demo users below |
| Guest booking engine | <http://localhost:8000/book/aurora> | none |
| Frappe Desk (developers) | <http://localhost:8000/desk> | `Administrator` / `admin` |
| Health check | <http://localhost:8000/api/method/ping> | none |

Demo users (password `TexDemo#2026` unless you changed `DEMO_PASSWORD` before the first start):

| User | Role | Scope |
| --- | --- | --- |
| `revenue@demo.tex` | Revenue Manager | hotel group (both hotels) |
| `agent@demo.tex` | Reservations / call-centre agent | hotel group |
| `finance@demo.tex` | Finance | hotel group |
| `beach.gm@demo.tex` | Hotel Admin | Aurora Beach Resort only |

Demo data (`kamra/tex/devtools/demo_seed.py`): enterprise "Aurora Hospitality (demo)", hotel
group "Aurora Riviera Collection" with **Aurora City Hotel** (Istanbul) and **Aurora Beach
Resort** (Antalya), published DE and GLOBAL contracts for this year and next, a DACH markup,
promo code `EARLY10`, extras, the booking site `aurora` and six demo bookings.

The staff app lives under `/kamra` (the Frappe app is still called `kamra`, ADR-001):
`/tex` on its own is not a page (404).

### What is sandbox-only

* **Payments:** the demo hotels use the *Mock* card gateway (environment Sandbox), bank
  transfer and pay-at-hotel. A card payment opens a "Sandbox payment page" where you pick
  *Simulate successful payment* or *Simulate declined payment*. No card data is asked for
  or sent anywhere.
* **E-mail:** no mail server is configured, so nothing is sent. Each booking e-mail attempt
  leaves a "TEX booking e-mail …" entry in Frappe's Error Log; the booking itself is fine.
* **Channels:** channel connections use the Sandbox adapter, which records deliveries and
  calls nothing.
* **Local-test settings** (applied on the first start): `developer_mode` on, public booking
  API rate limits raised to 1000 (`tex_public_search_limit`, `tex_public_write_limit`),
  scheduler enabled, site time zone Europe/Istanbul. The site is never flagged `tex_production`.
* **Code and DocType changes do not belong in this stack.** The `kamra` code is *copied* into
  the image when it is built. With `developer_mode` on, saving a DocType in Desk writes its
  JSON into the container's copy only. That copy is thrown away by the next `--build` or
  `down`/`up`; the change is then left in this stack's database only and never reaches
  your checkout or Git. Make code and DocType changes on a native bench
  ([NATIVE.md](NATIVE.md)), where your checkout is linked in.

## Requirements (measured)

* Docker Desktop 4.x (Windows 10/11 with WSL 2, macOS Intel or Apple Silicon) or Docker
  Engine with the Compose v2 plugin (Linux). BuildKit is required (default in both).
  Docker Desktop is free for personal use and small businesses; companies with more than
  250 employees or more than USD 10 million annual revenue need a paid Docker subscription.
  Docker Engine on Linux is free.
* **Disk: plan for ~10 GB free.** Measured here: `tex` image 2.24 GB (480 MB compressed),
  `mariadb:11.8` 458 MB, `redis:7-alpine` 58 MB, the build-only base images
  `python:3.14-slim-bookworm` 186 MB and `node:24-bookworm-slim` 332 MB, build cache 2.3 GB
  (reclaimable with `docker builder prune`), database volume 231 MB after the demo data and
  a Playwright run.
* **Memory: at least 2 GB for Docker, 4 GB recommended.** Measured in use after a
  Playwright run: `tex` 384 MiB, `db` 182 MiB, `redis` 7 MiB (about 0.6 GB together); peak
  use during the build was not measured. macOS: Docker Desktop *Settings → Resources →
  Memory*. Windows with WSL 2 has no memory slider: WSL may use half of the computer's
  memory by default, which is enough on an 8 GB machine; to change it, put `[wsl2]` and
  `memory=4GB` in `%UserProfile%\.wslconfig` and run `wsl --shutdown`.
* Internet access during the first build (Debian packages, PyPI, npm, GitHub). The running
  stack needs no internet access.

Measured times (x86_64 Linux, Docker 29.3, base images already downloaded):

| Step | Time |
| --- | --- |
| First build (`docker compose build`) | 6 min 34 s; 3 min 50 s of it was one slow 22 MB download on this network |
| Rebuild after changing repository code | about 5 s; needs no internet access |
| First start, `up -d` → healthy (site + apps + demo data) | 88–99 s (five fresh runs) |
| Later start, `up -d` → healthy (migrate only) | 28–33 s |
| Stop | under 1 s |

## Everyday commands

Run these in `deploy/tex-local`.

```bash
docker compose up -d                 # start (builds the image the first time)
docker compose ps                    # "healthy" = ready
docker compose logs -f tex           # follow the TEX container (Ctrl+C stops following only)
docker compose stop                  # stop, keep everything
docker compose down                  # stop and remove the containers, keep the data volumes
docker compose down -v               # DELETE all data (database + site) - next start is a fresh install
docker compose exec tex bash         # shell in the TEX container (bench, logs)
```

Inside the container (`docker compose exec tex bash`), the bench is `~/frappe-bench` and the
site is `tex.localhost`:

```bash
bench --site tex.localhost console               # Python console
bench --site tex.localhost mariadb               # SQL console
# free the demo inventory booked by test runs (keeps the demo-seed bookings)
bench --site tex.localhost execute kamra.tex.devtools.demo_seed.release_test_bookings
```

### Update to newer code

```bash
git pull                             # or download the new ZIP over the old folder
docker compose up -d --build         # rebuild; the site is migrated, data is kept
```

If you use the company-proxy lines in `.env` (see *Troubleshooting*), this command picks
them up by itself. A rebuild after a code change reuses the cached Frappe and `payments`
layers and needs no internet access.

`payments` is pinned: its `version-16` branch (the one for Frappe v16; `develop` already
declares Frappe v17) moves, so a newer commit is not verified with TEX. The pin is the commit
this setup was verified with, `cca07d9f9392e2ea0e521c5975151db9e4b6c321`. Build arguments
`FRAPPE_BRANCH` (v16.36.1), `PAYMENTS_BRANCH` (version-16), `PAYMENTS_REF` (the pin: a full
commit SHA, tag or branch; empty = the tip of `PAYMENTS_BRANCH`), `FRAPPE_REPO`,
`PAYMENTS_REPO` and `BENCH_VERSION` (5.31.0) can be overridden, for example
`docker compose build --build-arg PAYMENTS_REF= && docker compose up -d` to try the current
tip of `version-16` (not verified with TEX).

### Remove everything

```bash
docker compose down -v --rmi local   # containers, data volumes and the tex image
docker builder prune                 # build cache
```

## Configuration (`.env`)

Copy `.env.example` to `.env` next to `docker-compose.yml` and change what you need. Every
value has a default, so `.env` is optional.

| System | Create and edit `.env` |
| --- | --- |
| Windows (PowerShell) | `Copy-Item .env.example .env; notepad .env` - or for one setting: `Set-Content .env 'TEX_PORT=8010' -Encoding ascii` |
| macOS / Linux | `cp .env.example .env`, then any text editor - or: `echo 'TEX_PORT=8010' > .env` |

Keep `.env` plain text (UTF-8 or ANSI; Windows line endings are fine). In Windows
PowerShell 5.1, `echo … > .env` writes UTF-16, and then **every** `docker compose` command
in this folder fails with `unexpected character "\xff\xfe…" in variable name`: delete that
file and create it with one of the commands above. Notepad's *Save as* may add `.txt`;
opening the file with `notepad .env` avoids that.

| Variable | Default | Notes |
| --- | --- | --- |
| `TEX_PORT` | `8000` | port on your computer |
| `TEX_BIND` | `127.0.0.1` | interface the port is published on; see *Sharing on a network* |
| `TEX_SITE` | `tex.localhost` | internal site name; every host name is served by it (`bench use`), so no hosts-file edit is needed. Fixed by the first start |
| `TEX_TIME_ZONE` | `Europe/Istanbul` | site time zone (demo hotels are in Türkiye) |
| `ADMIN_PASSWORD` | `admin` | Frappe `Administrator` |
| `DEMO_PASSWORD` | `TexDemo#2026` | the four demo users |
| `DB_ROOT_PASSWORD` | `tex-local-root` | MariaDB root |

Passwords and `TEX_TIME_ZONE` are applied on the **first start only**. To change them later,
reset with `docker compose down -v` and start again. `TEX_SITE` is fixed by the first start
as well: if it differs later, the container stops with a message instead of creating a
second site (set it back, or reset). Put values containing `#` or `$` in single quotes in
`.env`.

## How it works

`entrypoint.sh` runs on every container start:

* **Every start:** points the bench at the compose services (`db_host=db`,
  `redis_cache/queue/socketio=redis://redis:6379`), links `sites/assets` to the assets of the
  current image, and waits for MariaDB and Redis.
* **First start** (no finished site in the `sites` volume): `bench new-site`, install
  `payments` and `kamra`, make sure the site has an `encryption_key` (TEX signs offer keys
  and payment links with it and refuses to work without one), `developer_mode`, rate limits,
  `bench use`, scheduler, time zone, then the demo data (`demo_seed.execute`). Two marker
  files in the site folder record progress: a first start that stops half-way is resumed or
  redone on the next start (the demo seed is idempotent; an unfinished install is dropped
  and recreated). To start from scratch instead: `docker compose down -v`.
* **Later starts:** `bench --site <site> migrate` only. Data is kept; demo data is never
  loaded again. If `migrate` fails (for example the database volume was deleted but the
  `sites` volume kept), the log says so and how to start from scratch.
* **Passwords stay out of logs:** `bench` writes every command line to `logs/bench.log`, so
  no password is put on one: `new-site` and `drop-site` run through `frappe_cli.py`, which
  takes the passwords from the container's environment, and the demo seed reads
  `DEMO_PASSWORD` from the environment itself.
* Then `honcho` runs the Frappe web server (`bench serve`, port 8000 in the container), the
  scheduler and two background workers (one for the `short` and `default` queues, one for
  `long`: the PMS outbox runs there, never ahead of holds and payments) in the foreground;
  `docker compose stop` shuts them down cleanly.

The site's `encryption_key` lives in `sites/tex.localhost/site_config.json` in the `sites`
volume. Losing the volume loses the key; that is fine for demo data.

The realtime (socket.io) server is not started: the staff app then refreshes live views
every 25 seconds instead of instantly (the same as on the development bench with
`bench serve`).

## Troubleshooting

**Port already in use** (`Bind for 127.0.0.1:8000 failed: port is already allocated`):
put `TEX_PORT=8010` (any free port) in `.env` - Windows PowerShell:
`Set-Content .env 'TEX_PORT=8010' -Encoding ascii`, macOS/Linux: `echo 'TEX_PORT=8010' > .env`
(both replace an existing `.env`; edit it instead if you have one) - then run
`docker compose up -d` and open `http://localhost:8010/kamra/tex`.

**Every `docker compose` command fails with `unexpected character … in variable name`:**
`.env` was saved as UTF-16 (Windows PowerShell `echo … > .env`). Delete it and create it
again as shown in *Configuration*.

**`tex` stays `starting` or becomes `unhealthy` / restarting:** read `docker compose logs tex`.
Lines starting with `[tex-local]` show each step and its duration. A failed first start
prints how to recover; a restart (`docker compose restart tex`) resumes it, and
`docker compose down -v && docker compose up -d` starts clean.

**The build fails while downloading** (TLS / certificate errors, timeouts): networks whose
proxy re-signs HTTPS (some company networks) need that network's root CA during the build.
Save it as a PEM file (your IT department has it) and add these three lines to `.env`
(they are in `.env.example`; this works the same on Windows, macOS and Linux):
```
COMPOSE_PATH_SEPARATOR=,
COMPOSE_FILE=docker-compose.yml,docker-compose.extra-ca.yml
TEX_EXTRA_CA_FILE=C:/Users/me/company-root-ca.pem
```
Then run `docker compose up -d --build`. Every `docker compose` command in this folder now
includes the optional override `docker-compose.extra-ca.yml`, so later rebuilds (*Update to
newer code*) use the certificate too. The certificate is passed as a BuildKit secret, used
only while downloading and never stored in the image. An HTTP proxy is set in Docker
Desktop (*Settings → Resources → Proxies*) or passed as build arguments:
`docker compose build --build-arg HTTPS_PROXY=http://proxy:3128`. Neither is needed on a
normal network.

**Apple Silicon (M1–M4):** every base image is multi-architecture and the image builds
natively for arm64 (not verified on a Mac yet; the verification run was on x86_64). If a
Python package has no arm64 wheel it is compiled during the build, which only takes longer.
As a fallback, build and run the x86_64 image under emulation (slower):
`DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d --build`.

**Windows line endings:** the shell scripts and the Procfile must keep LF line endings.
`deploy/tex-local/.gitattributes` makes Git keep LF for them even with `core.autocrlf=true`,
and the Dockerfile strips any `\r` again, so a symptom such as `bash\r: No such file or
directory` should not appear. If it does, re-clone with `git config --global core.autocrlf input`.
Use Docker Desktop with the WSL 2 backend.

**Changed a password in `.env` but it does not work:** passwords are set on the first start
only (see *Configuration*).

**Low disk space:** `docker system df` shows usage; `docker builder prune` frees the build
cache after a successful build.

**Frappe Desk shows the setup wizard** for `Administrator` at `/desk`: TEX does not need it.
Ignore Desk, or complete the wizard and keep the time zone **Europe/Istanbul** (the
wizard suggests your browser's zone). Frappe stores times without a zone: switching the
site to a zone west of Istanbul (Europe/Berlin, Europe/London, …) makes the demo contracts,
published in Istanbul time, count as not yet effective, and the booking engine finds no
offers for up to the hours of difference.

**Playwright E2E against this stack** (developers, from the repository's `frontend/`):
```bash
npm ci && npx playwright install chromium
TEX_E2E_BASE=http://localhost:8000 TEX_E2E_PASSWORD='TexDemo#2026' \
  npx playwright test -c e2e shell.spec.ts booking.spec.ts crs.spec.ts --project=desktop
```
Repeated runs book real inventory at the demo hotels; free it with `release_test_bookings`
(see *Everyday commands*).

## Sharing on a network

By default the port is published on `127.0.0.1` only. `TEX_BIND=0.0.0.0` makes it reachable
from other computers on your network; do that only on a trusted network, and only after
setting your own passwords in `.env` **before the first start**. It is still a development
server with `developer_mode` on and is never suitable for the internet or real data.

## Without Docker

To run TEX Engine directly on macOS, Linux or Windows (WSL 2) with a native bench, see
[NATIVE.md](NATIVE.md).

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | the stack (db, redis, tex) |
| `Dockerfile` | the `tex` image; build context is the repository root |
| `Dockerfile.dockerignore` | keeps the build context small and secret-free (`.git`, `node_modules`, test output, `.env`, keys) |
| `entrypoint.sh` | first-start setup / later-start migrate, then the processes |
| `frappe_cli.py` | runs a Frappe command with passwords from the environment, so they never reach `logs/bench.log` (also used by `setup-local.sh`) |
| `Procfile` | web, scheduler, worker (`short,default`), worker_long (`long`) (run by honcho) |
| `with-extra-ca.sh` | build-time helper for the optional `extra_ca` secret |
| `docker-compose.extra-ca.yml` | optional override that passes a network root CA to the build |
| `.env.example` | settings template |
| `.gitattributes` | keeps LF line endings for the container scripts |
| `NATIVE.md`, `setup-local.sh` | the same TEX Engine without Docker (native bench) |
