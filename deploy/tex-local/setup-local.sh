#!/usr/bin/env bash
#
# TEX Engine - native local bench (no Docker) for a laptop or dev machine.
#
#   deploy/tex-local/setup-local.sh [options]          (--help; guide: NATIVE.md)
#
# Builds a Frappe bench next to your checkout (default: ../tex-bench): Frappe v16.25.0
# + payments (develop, pinned to a verified commit) + this repository linked in as the
# `kamra` app, one site with developer mode and the TEX demo data (two hotels,
# contracts, booking site "aurora", demo users).
#
# FOR LOCAL TESTING ONLY. The default passwords (admin / TexDemo#2026) are public
# knowledge. Never put real guest or payment data on this bench and never expose
# it to a network you do not trust.
#
# Safe to re-run: finished steps are skipped and the site is never dropped unless
# you pass --reset. Needs no root; when an OS package is missing it prints the
# install command instead of running sudo.
#
# Part of TEX Engine (fork of Kamra PMS), AGPL-3.0 - see license.txt.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
DEFAULT_REPO=$(cd "$SCRIPT_DIR/../.." && pwd -P)

FRAPPE_BRANCH=${TEX_FRAPPE_BRANCH:-v16.25.0}
PAYMENTS_URL=${TEX_PAYMENTS_URL:-https://github.com/frappe/payments}
PAYMENTS_BRANCH=${TEX_PAYMENTS_BRANCH:-develop}
# payments' develop moves and already declares Frappe v17: use the commit this setup was
# verified with. TEX_PAYMENTS_REF= (set but empty) keeps the tip of TEX_PAYMENTS_BRANCH.
PAYMENTS_REF=${TEX_PAYMENTS_REF-86fefa9faf8ad825fe6f08c4753acfe44817900b}
DEFAULT_ADMIN_PASSWORD='admin'
DEFAULT_DEMO_PASSWORD='TexDemo#2026'
DEMO_SLUG=aurora

usage() {
	cat <<'EOF'
Usage: deploy/tex-local/setup-local.sh [options]

Creates (or completes) a local TEX Engine bench. LOCAL TESTING ONLY.

Options (environment variable in brackets):
  --dir DIR                bench directory                 [TEX_DIR]
                           default: tex-bench next to the checkout (../tex-bench);
                           must not be inside the checkout
  --site NAME              site name                       [TEX_SITE]    default tex.localhost
  --port N                 web port (3000-60000)           [TEX_PORT]    default 8000
                           also sets realtime N+1000, private Redis N+3000 (queue)
                           and N+5000 (cache): 8000 -> 9000, 11000, 13000
  --db-root-password PW    MariaDB root password           [TEX_DB_ROOT_PASSWORD]
                           asked for when a site has to be created and none is given
  --admin-password PW      site Administrator password     [TEX_ADMIN_PASSWORD] default admin
  --demo-password PW       password of the demo users      [TEX_DEMO_PASSWORD]  default TexDemo#2026
  --repo PATH              TEX Engine checkout to link in  [TEX_REPO]    default: this checkout
  --python PATH            Python 3.14 interpreter         [TEX_PYTHON]  default: auto-detect
  --db-host HOST           MariaDB host                    [TEX_DB_HOST] default 127.0.0.1
  --db-port N              MariaDB port                    [TEX_DB_PORT] default 3306
  --redis bench|URL        "bench" (default): private Redis servers that `bench start`
                           runs on 127.0.0.1; or the URL of a Redis you already run,
                           e.g. redis://127.0.0.1:6379/2 (use a Redis or db index of
                           its own: rebuilding assets flushes it)       [TEX_REDIS]
  --bind ADDR              address the web and realtime servers listen on
                           default 127.0.0.1 (this computer only); 0.0.0.0 = your
                           whole network, e.g. to try the booking engine on a phone [TEX_BIND]
  --time-zone TZ           time zone of the site and the demo hotels, set when the demo
                           data is loaded                  [TEX_TIME_ZONE] default Europe/Istanbul
  --adopt                  allow --dir to name a bench this script did not create (it
                           rewrites that bench's ports, Redis, Procfile and default site)
  --reset                  drop the site (a backup is kept under <dir>/archived/sites) and
                           create it again with fresh demo data
  -y, --yes                answer yes to questions (installing bench or Python 3.14,
                           confirming --reset)
  -h, --help               this help

Other environment variables: TEX_FRAPPE_BRANCH (v16.25.0), TEX_PAYMENTS_URL,
TEX_PAYMENTS_BRANCH (develop), TEX_PAYMENTS_REF (the verified payments commit; empty =
the tip of TEX_PAYMENTS_BRANCH).

Re-running with no options keeps the site, port, bind address, Redis choice and time
zone that were used last time (saved in <dir>/tex-local/settings.env; passwords are not
saved) and migrates the site (new DocTypes and patches after a git pull).
EOF
}

# ---------------------------------------------------------------- output helpers
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
	C_B=$'\033[1m' C_G=$'\033[32m' C_Y=$'\033[33m' C_R=$'\033[31m' C_D=$'\033[2m' C_N=$'\033[0m'
else
	C_B='' C_G='' C_Y='' C_R='' C_D='' C_N=''
fi
info() { printf '%s\n' "$*"; }
warn() { printf '%swarning:%s %s\n' "$C_Y" "$C_N" "$*" >&2; }
die() { printf '%serror:%s %s\n' "$C_R" "$C_N" "$*" >&2; exit 1; }

T_START=$(date +%s)
STEP_NO=0
STEP_T=0
STEP_NAME=''
TIMINGS=''
step() {
	STEP_NO=$((STEP_NO + 1))
	STEP_NAME=$1
	STEP_T=$(date +%s)
	printf '\n%s==> [%d] %s%s\n' "$C_B" "$STEP_NO" "$STEP_NAME" "$C_N"
}
_step_end() { # status detail
	local secs=$(($(date +%s) - STEP_T))
	TIMINGS="${TIMINGS}$(printf '  %-4s %-36s %5ss  %s' "$1" "$STEP_NAME" "$secs" "$2")"$'\n'
}
ok() { printf '%s[ok]%s %s %s(%ss)%s\n' "$C_G" "$C_N" "$*" "$C_D" "$(($(date +%s) - STEP_T))" "$C_N"; _step_end ok "$*"; }
skip() { printf '%s[skip]%s %s\n' "$C_G" "$C_N" "$*"; _step_end skip "$*"; }

has() { command -v "$1" >/dev/null 2>&1; }

confirm() { # question -> 0 when yes
	if [ "$ASSUME_YES" = 1 ]; then
		info "$1 -> yes (--yes)"
		return 0
	fi
	if (exec </dev/tty) 2>/dev/null; then
		local ans=''
		printf '%s [y/N] ' "$1" >/dev/tty
		IFS= read -r ans </dev/tty || ans=''
		case "$ans" in y | Y | yes | Yes | YES) return 0 ;; esac
	fi
	return 1
}

ask_secret() { # varname prompt -> 1 when there is no terminal to ask on
	local ans=''
	(exec </dev/tty) 2>/dev/null || return 1
	printf '%s' "$2" >/dev/tty
	IFS= read -r -s ans </dev/tty || ans=''
	printf '\n' >/dev/tty
	printf -v "$1" '%s' "$ans"
}

# ---------------------------------------------------------------- options
OPT_DIR='' OPT_SITE='' OPT_PORT='' OPT_REPO='' OPT_PYTHON='' OPT_DB_HOST='' OPT_DB_PORT=''
OPT_REDIS='' OPT_BIND='' OPT_TZ=''
DB_ROOT_PASSWORD=${TEX_DB_ROOT_PASSWORD:-}
ADMIN_PASSWORD=${TEX_ADMIN_PASSWORD:-$DEFAULT_ADMIN_PASSWORD}
DEMO_PASSWORD=${TEX_DEMO_PASSWORD:-$DEFAULT_DEMO_PASSWORD}
ASSUME_YES=0
RESET=0
ADOPT=0

while [ $# -gt 0 ]; do
	arg=$1
	val=''
	has_val=0
	case "$arg" in
	--*=*)
		val=${arg#*=}
		arg=${arg%%=*}
		has_val=1
		;;
	esac
	case "$arg" in
	-h | --help)
		usage
		exit 0
		;;
	-y | --yes) ASSUME_YES=1 ;;
	--reset) RESET=1 ;;
	--adopt) ADOPT=1 ;;
	--dir | --site | --port | --db-root-password | --admin-password | --demo-password | --repo | --python | \
		--db-host | --db-port | --redis | --bind | --time-zone)
		if [ "$has_val" = 0 ]; then
			[ $# -ge 2 ] || die "$arg needs a value (see --help)"
			val=$2
			shift
		fi
		case "$arg" in
		--dir) OPT_DIR=$val ;;
		--site) OPT_SITE=$val ;;
		--port) OPT_PORT=$val ;;
		--db-root-password) DB_ROOT_PASSWORD=$val ;;
		--admin-password) ADMIN_PASSWORD=$val ;;
		--demo-password) DEMO_PASSWORD=$val ;;
		--repo) OPT_REPO=$val ;;
		--python) OPT_PYTHON=$val ;;
		--db-host) OPT_DB_HOST=$val ;;
		--db-port) OPT_DB_PORT=$val ;;
		--redis) OPT_REDIS=$val ;;
		--bind) OPT_BIND=$val ;;
		--time-zone) OPT_TZ=$val ;;
		esac
		;;
	*) die "unknown option: $1 (see --help)" ;;
	esac
	shift
done

# shellcheck disable=SC2088 # matches a literal "~/" the shell did not expand (e.g. --dir=~/x)
expand_home() { case "$1" in "~") printf '%s' "$HOME" ;; "~/"*) printf '%s/%s' "$HOME" "${1#"~/"}" ;; *) printf '%s' "$1" ;; esac; }

REPO_EXPLICIT=0
if [ -n "$OPT_REPO" ] || [ -n "${TEX_REPO:-}" ]; then REPO_EXPLICIT=1; fi
REPO=$(expand_home "${OPT_REPO:-${TEX_REPO:-$DEFAULT_REPO}}")
[ -d "$REPO" ] || die "--repo: no such directory: $REPO"
REPO=$(cd "$REPO" && pwd -P)

# default: tex-bench next to the checkout (never inside it: git would pick up the bench's
# env, passwords and backups, and the Docker build context would copy them)
REPO_PARENT=$(dirname "$REPO")
DIR=$(expand_home "${OPT_DIR:-${TEX_DIR:-${REPO_PARENT%/}/tex-bench}}")
case "$DIR" in /*) ;; *) DIR="$PWD/$DIR" ;; esac
case "$DIR" in *[[:space:]]*) die "the bench directory must not contain spaces (Frappe bench does not support them): $DIR" ;; esac
DIR=${DIR%/}
[ -n "$DIR" ] || die "--dir must not be the root directory"
case "$DIR/" in "$REPO/"*) die "the bench directory $DIR is inside the TEX Engine checkout $REPO. Put it next to the checkout instead, e.g. --dir ${REPO_PARENT%/}/tex-bench (the default)" ;; esac
mkdir -p "$(dirname "$DIR")"
DIR="$(cd "$(dirname "$DIR")" && pwd -P)/$(basename "$DIR")"
case "$DIR/" in "$REPO/"*) die "the bench directory $DIR is inside the TEX Engine checkout $REPO. Put it next to the checkout instead, e.g. --dir ${REPO_PARENT%/}/tex-bench (the default)" ;; esac
SETTINGS="$DIR/tex-local/settings.env"

# settings of the previous run (never passwords)
S_SITE='' S_PORT='' S_BIND='' S_REDIS='' S_DB_HOST='' S_DB_PORT='' S_TZ=''
if [ -f "$SETTINGS" ]; then
	while IFS='=' read -r k v || [ -n "$k" ]; do
		case "$k" in
		SITE) S_SITE=$v ;;
		PORT) S_PORT=$v ;;
		BIND) S_BIND=$v ;;
		REDIS) S_REDIS=$v ;;
		DB_HOST) S_DB_HOST=$v ;;
		DB_PORT) S_DB_PORT=$v ;;
		TIME_ZONE) S_TZ=$v ;;
		esac
	done <"$SETTINGS"
fi

SITE=${OPT_SITE:-${TEX_SITE:-${S_SITE:-tex.localhost}}}
PORT=${OPT_PORT:-${TEX_PORT:-${S_PORT:-8000}}}
BIND=${OPT_BIND:-${TEX_BIND:-${S_BIND:-127.0.0.1}}}
REDIS=${OPT_REDIS:-${TEX_REDIS:-${S_REDIS:-bench}}}
DB_HOST=${OPT_DB_HOST:-${TEX_DB_HOST:-${S_DB_HOST:-127.0.0.1}}}
DB_PORT=${OPT_DB_PORT:-${TEX_DB_PORT:-${S_DB_PORT:-3306}}}
TIME_ZONE=${OPT_TZ:-${TEX_TIME_ZONE:-${S_TZ:-Europe/Istanbul}}}
TZ_EXPLICIT=0
if [ -n "$OPT_TZ" ] || [ -n "${TEX_TIME_ZONE:-}" ]; then TZ_EXPLICIT=1; fi

case "$SITE" in
*[!a-z0-9.-]* | "" | .* | -* | *. | *-) die "--site must be a lower-case host name such as tex.localhost (got '$SITE')" ;;
esac
case "$PORT" in *[!0-9]* | "") die "--port must be a number (got '$PORT')" ;; esac
[ "$PORT" -ge 3000 ] && [ "$PORT" -le 60000 ] || die "--port must be between 3000 and 60000 (got $PORT)"
case "$DB_PORT" in *[!0-9]* | "") die "--db-port must be a number (got '$DB_PORT')" ;; esac
case "$BIND" in *[[:space:]]* | "") die "--bind must be an address such as 127.0.0.1 or 0.0.0.0" ;; esac
case "$REDIS" in bench | redis://* | rediss://* | unix://*) ;; *) die "--redis must be 'bench' or a redis:// URL (got '$REDIS')" ;; esac
case "$TIME_ZONE" in "" | *[!A-Za-z0-9/_+-]*) die "--time-zone must be an IANA time zone such as Europe/Istanbul (got '$TIME_ZONE')" ;; esac
[ -f "$REPO/kamra/hooks.py" ] && [ -f "$REPO/pyproject.toml" ] || die "$REPO does not look like a TEX Engine checkout (no kamra/hooks.py)"
[ -n "$ADMIN_PASSWORD" ] || die "--admin-password must not be empty"
[ -n "$DEMO_PASSWORD" ] || die "--demo-password must not be empty"

SOCKETIO_PORT=$((PORT + 1000))
REDIS_QUEUE_PORT=$((PORT + 3000))
REDIS_CACHE_PORT=$((PORT + 5000))
FILE_WATCHER_PORT=$((PORT - 1213)) # 8000 -> 6787, Frappe's default for `bench watch`

OS=linux
case "$(uname -s)" in
Darwin) OS=mac ;;
Linux) if grep -qi microsoft /proc/version 2>/dev/null; then OS=wsl; fi ;;
MINGW* | MSYS* | CYGWIN*) die "Frappe does not run natively on Windows. Use WSL2 (Ubuntu) - see deploy/tex-local/NATIVE.md" ;;
*) warn "untested operating system $(uname -s); continuing" ;;
esac

[ "$(id -u)" != 0 ] || die "do not run this as root (bench refuses to). Run it as your normal user; it prints any sudo command it needs."

# ---------------------------------------------------------------- python helpers
PY=''
TMPD=$(mktemp -d "${TMPDIR:-/tmp}/tex-local.XXXXXX")
# Small helpers run with the base Python 3.14 (no third-party modules).
cat >"$TMPD/helper.py" <<'PYEOF'
import json, os, socket, sys
from urllib.parse import unquote, urlparse

def resp(host, port, *cmd, password=None, user=None, db=None, timeout=3.0):
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        def send(*parts):
            out = b"*%d\r\n" % len(parts)
            for p in parts:
                p = p.encode() if isinstance(p, str) else p
                out += b"$%d\r\n%s\r\n" % (len(p), p)
            s.sendall(out)
            return s.recv(65536)
        if password:
            r = send("AUTH", *([user] if user else []), password)
            if not r.startswith(b"+OK"):
                raise SystemExit("AUTH failed: " + r.decode(errors="replace").strip())
        if db:
            send("SELECT", str(db))
        return send(*cmd)
    finally:
        s.close()

cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "port-open":            # host port -> exit 0 when something accepts connections
    try:
        socket.create_connection((args[0], int(args[1])), timeout=1).close()
    except OSError:
        sys.exit(1)
elif cmd == "redis-ping":         # host port -> exit 0 on PONG
    try:
        sys.exit(0 if resp(args[0], int(args[1]), "PING").startswith(b"+PONG") else 1)
    except OSError:
        sys.exit(1)
elif cmd == "redis-ping-url":     # url -> exit 0 on PONG, else print why
    u = urlparse(args[0])
    if u.scheme == "unix":
        print("unix:// URLs are not checked; make sure the socket is reachable"); sys.exit(0)
    if u.scheme == "rediss":
        print("rediss:// (TLS) is not checked here; continuing"); sys.exit(0)
    try:
        r = resp(u.hostname or "127.0.0.1", u.port or 6379, "PING",
                 password=unquote(u.password) if u.password else None,
                 user=unquote(u.username) if u.username else None,
                 db=(u.path or "/").strip("/") or None)
    except (OSError, SystemExit) as e:
        print(e); sys.exit(1)
    if not r.startswith(b"+PONG"):
        print(r.decode(errors="replace").strip()); sys.exit(1)
elif cmd == "redis-dir":          # host port -> the server's working directory
    r = resp(args[0], int(args[1]), "CONFIG", "GET", "dir").decode(errors="replace")
    parts = r.split("\r\n")
    print(parts[4] if len(parts) > 4 else "")
elif cmd == "json-set":           # file key=string | key:=<json> ...
    path = args[0]
    data = {}
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
    for kv in args[1:]:
        k, v = kv.split("=", 1)
        if k.endswith(":"):
            data[k[:-1]] = json.loads(v)
        else:
            data[k] = v
    tmp = path + ".tex-local.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
elif cmd == "json-get":           # file key -> value (empty when missing)
    try:
        with open(args[0]) as f:
            v = json.load(f).get(args[1])
    except (OSError, ValueError):
        v = None
    print("" if v is None else (v if isinstance(v, str) else json.dumps(v)))
elif cmd == "json-list":          # args -> JSON list of strings (also a Python literal, for bench execute --args)
    print(json.dumps(args))
elif cmd == "conf-flag":          # file key -> 1 when the value is truthy for Python (as frappe.conf.get sees it)
    try:
        with open(args[0]) as f:
            v = json.load(f).get(args[1])
    except (OSError, ValueError):
        v = None
    print(1 if v else 0)
elif cmd == "tz-ok":              # name -> exit 0 when it is a time zone Python knows
    import zoneinfo
    try:
        zoneinfo.ZoneInfo(args[0])
    except Exception:
        sys.exit(1)
elif cmd == "mycnf":              # path (password from TEX_LOCAL_PW) -> client option file
    pw = os.environ.get("TEX_LOCAL_PW", "").replace("\\", "\\\\").replace('"', '\\"')
    fd = os.open(args[0], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write('[client]\nuser=root\npassword="%s"\n' % pw)
else:
    sys.exit("unknown helper " + cmd)
PYEOF
pyhelp() { "$PY" "$TMPD/helper.py" "$@"; }

STARTED_REDIS=''
stop_setup_redis() {
	local kind pidf pid i
	for kind in $STARTED_REDIS; do
		pidf="$DIR/config/pids/redis_$kind.pid"
		if [ -f "$pidf" ]; then
			pid=$(cat "$pidf" 2>/dev/null || true)
			if [ -n "$pid" ] && kill "$pid" 2>/dev/null; then
				i=0
				while kill -0 "$pid" 2>/dev/null && [ $i -lt 50 ]; do
					sleep 0.2
					i=$((i + 1))
				done
				info "stopped the private Redis ($kind) that setup started"
			fi
		fi
	done
	STARTED_REDIS=''
}
cleanup() {
	stop_setup_redis
	rm -rf "$TMPD"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------- prerequisites
PROBLEMS=''
problem() { PROBLEMS="${PROBLEMS}  - $*"$'\n'; }

if [ "$OS" = mac ]; then
	HINT_BASE="brew install git redis mariadb@11.8 mariadb-connector-c pkgconf uv node@24 && npm install -g yarn   (then add mariadb@11.8 and node@24 to PATH, see NATIVE.md)"
else
	HINT_BASE="sudo apt install -y git curl build-essential pkg-config libmariadb-dev mariadb-server mariadb-client redis-server"
fi

bench_complete() {
	[ -x "$DIR/env/bin/python" ] && [ -f "$DIR/apps/frappe/frappe/__init__.py" ] && [ -f "$DIR/sites/common_site_config.json" ]
}
NEED_INIT=1
if bench_complete; then NEED_INIT=0; fi
# a complete bench without our settings file was not made by this script: reconfiguring it
# (ports, Redis, Procfile, default site) would affect every site on it
if [ "$NEED_INIT" = 0 ] && [ ! -f "$SETTINGS" ] && [ "$ADOPT" != 1 ]; then
	die "$DIR is an existing Frappe bench that this script did not create. Setting it up for TEX would rewrite its ports, Redis settings, Procfile and default site for all of its sites. Choose a new --dir, or pass --adopt if that is really what you want."
fi

site_exists() { [ -f "$DIR/sites/$SITE/site_config.json" ]; }

find_python() {
	local cand='' out ver
	if [ -n "$OPT_PYTHON" ] || [ -n "${TEX_PYTHON:-}" ]; then
		cand=$(expand_home "${OPT_PYTHON:-$TEX_PYTHON}")
	elif has python3.14; then
		cand=$(command -v python3.14)
	elif has uv && out=$(uv python find 3.14 2>/dev/null); then
		cand=$out
	fi
	if [ -z "$cand" ] && has uv; then
		if confirm "Python 3.14 was not found. Install it with 'uv python install 3.14' (per user, no admin rights)?"; then
			uv python install 3.14 && cand=$(uv python find 3.14 2>/dev/null || true)
		fi
	fi
	if [ -z "$cand" ]; then
		problem "Python 3.14 not found. Install it with: uv python install 3.14   (or pass --python PATH)"
		return 0
	fi
	# a virtualenv's python is replaced by its base interpreter (the bench gets its own env)
	out=$("$cand" -c 'import sys; b = getattr(sys, "_base_executable", "") if sys.prefix != sys.base_prefix else ""; print("%d.%d %s" % (sys.version_info[0], sys.version_info[1], b or sys.executable))' 2>/dev/null) || {
		problem "cannot run $cand"
		return 0
	}
	ver=${out%% *}
	if [ "$ver" != 3.14 ]; then
		problem "$cand is Python $ver; Frappe v16 needs Python 3.14 (uv python install 3.14)"
		return 0
	fi
	PY=${out#* }
}

step "Checking prerequisites"
has git || problem "git not found. Install: $HINT_BASE"
if ! has uv; then
	if [ "$OS" = mac ]; then
		problem "uv not found (bench uses it to install Python packages). Install: brew install uv"
	else
		problem "uv not found (bench uses it to install Python packages). Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
	fi
fi
find_python
if [ -n "$PY" ] && ! pyhelp tz-ok "$TIME_ZONE"; then
	problem "--time-zone $TIME_ZONE is not a time zone Python knows (use an IANA name such as Europe/Istanbul)"
fi
if has node; then
	NODE_MAJOR=$(node -v 2>/dev/null | sed 's/^v//; s/\..*//')
	case "$NODE_MAJOR" in *[!0-9]* | "") NODE_MAJOR=0 ;; esac
	if [ "$NODE_MAJOR" -lt 24 ]; then
		problem "Node $(node -v) is too old; Frappe v16 needs Node 24 (see NATIVE.md: nvm install 24, or brew install node@24)"
	elif [ "$NODE_MAJOR" -gt 24 ]; then
		warn "Node $(node -v): Frappe v16 is tested with Node 24"
	fi
else
	problem "node not found; Frappe v16 needs Node 24 (see NATIVE.md: nvm install 24, or brew install node@24)"
fi
if has yarn; then
	case "$(yarn --version 2>/dev/null)" in
	1.*) ;;
	*) problem "yarn $(yarn --version 2>/dev/null) found; Frappe needs Yarn 1 (classic): npm install -g yarn" ;;
	esac
else
	problem "yarn not found. Install: npm install -g yarn"
fi
MYSQL_BIN=''
if has mariadb; then MYSQL_BIN=mariadb; elif has mysql; then MYSQL_BIN=mysql; fi
[ -n "$MYSQL_BIN" ] || problem "MariaDB client (mariadb) not found. Install: $HINT_BASE"
if [ "$REDIS" = bench ]; then
	if has redis-server; then
		REDIS_VER=$(redis-server --version 2>/dev/null | sed 's/.* v=\([0-9]*\)\..*/\1/')
		case "$REDIS_VER" in *[!0-9]* | "") REDIS_VER=0 ;; esac
		[ "$REDIS_VER" -ge 6 ] || warn "redis-server $REDIS_VER.x is old; Frappe v16 expects Redis 6 or newer"
	else
		problem "redis-server not found (the bench runs its own private Redis; the Redis service does not need to be running). Install: $HINT_BASE   - or pass --redis redis://HOST:PORT/DB to use a Redis you already run"
	fi
elif [ -n "$PY" ]; then
	if ! out=$(pyhelp redis-ping-url "$REDIS" 2>&1); then
		problem "cannot reach Redis at $REDIS: $out"
	fi
fi
if [ "$NEED_INIT" = 1 ]; then
	# only needed to build Frappe's Python dependencies (mysqlclient)
	has cc || has gcc || has clang || problem "no C compiler. Install: $([ "$OS" = mac ] && echo 'xcode-select --install' || echo 'sudo apt install -y build-essential')"
	if has pkg-config; then
		PKGP=${PKG_CONFIG_PATH:-}
		if [ "$OS" = mac ] && has brew; then PKGP="$(brew --prefix mariadb-connector-c 2>/dev/null)/lib/pkgconfig${PKGP:+:$PKGP}"; fi
		PKG_CONFIG_PATH=$PKGP pkg-config --exists mysqlclient || PKG_CONFIG_PATH=$PKGP pkg-config --exists mariadb ||
			PKG_CONFIG_PATH=$PKGP pkg-config --exists libmariadb ||
			problem "MariaDB client development files not found (needed to build mysqlclient). Install: $([ "$OS" = mac ] && echo 'brew install mariadb-connector-c' || echo 'sudo apt install -y libmariadb-dev')"
	else
		problem "pkg-config not found. Install: $([ "$OS" = mac ] && echo 'brew install pkgconf' || echo 'sudo apt install -y pkg-config')"
	fi
fi
if [ "$OS" = wsl ]; then
	case "$DIR:$REPO" in /mnt/*) warn "the bench or the checkout is on the Windows drive (/mnt/...): that is very slow. Clone into your WSL home (~/) instead." ;; esac
fi

# MariaDB: the root password is needed to create or drop the site's database
NEED_ROOT=0
if [ "$RESET" = 1 ] || ! site_exists; then NEED_ROOT=1; fi
if [ "$NEED_ROOT" = 1 ] && [ -z "$DB_ROOT_PASSWORD" ]; then
	ask_secret DB_ROOT_PASSWORD "MariaDB root password (for $DB_HOST:$DB_PORT): " ||
		problem "the MariaDB root password is needed to create the site: pass --db-root-password or set TEX_DB_ROOT_PASSWORD"
fi
if [ -n "$MYSQL_BIN" ] && [ -n "$PY" ] && [ -n "$DB_ROOT_PASSWORD" ]; then
	(
		export TEX_LOCAL_PW="$DB_ROOT_PASSWORD"
		pyhelp mycnf "$TMPD/root.cnf"
	)
	if db_info=$("$MYSQL_BIN" --defaults-extra-file="$TMPD/root.cnf" --protocol=TCP -h "$DB_HOST" -P "$DB_PORT" -N -B \
		-e "SELECT VERSION(), @@character_set_server, @@collation_server" 2>"$TMPD/db.err"); then
		# shellcheck disable=SC2086
		set -- $db_info
		info "MariaDB $1 at $DB_HOST:$DB_PORT (server charset $2 / $3)"
		case "$1" in
		*MariaDB*)
			DB_MAJOR=${1%%.*}
			DB_MINOR=${1#*.}
			DB_MINOR=${DB_MINOR%%.*}
			case "$DB_MAJOR$DB_MINOR" in *[!0-9]* | "") DB_MAJOR=0 DB_MINOR=0 ;; esac
			if [ "$DB_MAJOR" -gt 11 ] || [ "$DB_MAJOR" -lt 10 ] || { [ "$DB_MAJOR" = 10 ] && [ "$DB_MINOR" -lt 6 ]; }; then
				warn "MariaDB ${1%%-*} is outside the versions Frappe v16 is used with here (10.6-11.8; tested: 10.11 natively, 11.8 in Docker). If something fails, use MariaDB 11.8 (macOS: brew install mariadb@11.8)."
			fi
			;;
		*) warn "this does not look like MariaDB ($1); Frappe v16 is tested with MariaDB 10.6-11.8" ;;
		esac
		if [ "$2" != utf8mb4 ] || [ "$3" != utf8mb4_unicode_ci ]; then
			warn "MariaDB should use utf8mb4 / utf8mb4_unicode_ci (it uses $2 / $3). Add the config snippet from NATIVE.md and restart MariaDB."
		fi
		# ON by default from MariaDB 11.6.2 (ADR-063); a server without the variable prints nothing
		snapshot=$("$MYSQL_BIN" --defaults-extra-file="$TMPD/root.cnf" --protocol=TCP -h "$DB_HOST" -P "$DB_PORT" -N -B \
			-e "SELECT @@GLOBAL.innodb_snapshot_isolation" 2>/dev/null || true)
		if [ "$snapshot" = 1 ]; then
			warn "MariaDB has innodb_snapshot_isolation ON: a booking that waited for the last room would get an error instead of \"sold out\". Add loose-innodb_snapshot_isolation = 0 from the config snippet in NATIVE.md and restart MariaDB."
		fi
	else
		problem "cannot log in to MariaDB as root at $DB_HOST:$DB_PORT: $(tr '\n' ' ' <"$TMPD/db.err")
      Is MariaDB running (brew services start mariadb@11.8 / sudo service mariadb start)?
      Does root have a password? See NATIVE.md 'MariaDB root password'."
	fi
elif [ "$NEED_ROOT" = 0 ]; then
	info "site $SITE exists; MariaDB root password not needed (the site's own database login is used)"
fi

if [ -n "$PROBLEMS" ]; then
	printf '\n%sSetup cannot continue:%s\n%s\n' "$C_R" "$C_N" "$PROBLEMS" >&2
	printf 'Fix these (deploy/tex-local/NATIVE.md shows how for each system) and run this script again.\n' >&2
	exit 1
fi

# bench (frappe-bench); honcho, which runs `bench start`, comes with it
BENCH=$(command -v bench 2>/dev/null || true)
if [ -z "$BENCH" ]; then
	UV_BIN=$(uv tool dir --bin 2>/dev/null || true)
	if [ -n "$UV_BIN" ] && [ -x "$UV_BIN/bench" ]; then BENCH="$UV_BIN/bench"; fi
fi
if [ -z "$BENCH" ]; then
	if confirm "The Frappe 'bench' command is not installed. Install it now with 'uv tool install frappe-bench' (per user)?"; then
		uv tool install frappe-bench
		UV_BIN=$(uv tool dir --bin)
		BENCH="$UV_BIN/bench"
		[ -x "$BENCH" ] || die "bench was installed but $BENCH is missing"
	else
		die "bench is required. Install it with: uv tool install frappe-bench   (or: pip install --user frappe-bench, with uv on PATH), then re-run."
	fi
fi
BENCH_ON_PATH=1
case ":$PATH:" in *":$(dirname "$BENCH"):"*) ;; *)
	BENCH_ON_PATH=0
	PATH="$(dirname "$BENCH"):$PATH"
	export PATH
	;;
esac
BENCH_VERSION=$("$BENCH" --version 2>/dev/null | tail -n 1 || true)
case "$BENCH_VERSION" in 5.*) ;; *) warn "bench $BENCH_VERSION: this script is tested with bench 5.31" ;; esac

info "python  $PY"
info "node    $(node -v)   yarn $(yarn --version)   git $(git --version | sed 's/git version //')"
info "bench   $BENCH_VERSION ($BENCH)"
if [ "$REDIS" = bench ]; then
	info "redis   private to this bench on 127.0.0.1:$REDIS_QUEUE_PORT (queue) and :$REDIS_CACHE_PORT (cache)"
else
	info "redis   $REDIS"
fi
info "target  $DIR  site $SITE  port $PORT (realtime $SOCKETIO_PORT)  listening on $BIND"

# ports of a new bench must be free (on a re-run they may belong to this bench, running)
PORT_LIST="$PORT:web $SOCKETIO_PORT:realtime"
if [ "$REDIS" = bench ]; then PORT_LIST="$PORT_LIST $REDIS_QUEUE_PORT:redis-queue $REDIS_CACHE_PORT:redis-cache"; fi
for pl in $PORT_LIST; do
	p=${pl%%:*}
	if pyhelp port-open 127.0.0.1 "$p"; then
		if [ "$NEED_INIT" = 1 ]; then
			die "port $p (${pl#*:}) is already in use by another program; choose another --port (it also moves the realtime and Redis ports)"
		fi
		info "note: port $p (${pl#*:}) is in use - fine if this bench is running (bench start)"
	fi
done
ok "prerequisites present"

bench_in() { (cd "$DIR" && "$BENCH" "$@"); }
env_py() { (cd "$DIR" && "$DIR/env/bin/python" -P "$@"); }
# Frappe commands that take a password: `bench ...` writes its whole command line to
# logs/bench.log, so these run through frappe_cli.py, which reads "@env:NAME" arguments
# from the environment (the caller exports them in a subshell).
frappe_cli() { (cd "$DIR/sites" && "$DIR/env/bin/python" "$SCRIPT_DIR/frappe_cli.py" "$@"); }
[ -f "$SCRIPT_DIR/frappe_cli.py" ] || die "$SCRIPT_DIR/frappe_cli.py is missing (it comes with this script)"

# never touch a bench that has a live site (tex_production), --reset included
if [ "$NEED_INIT" = 0 ]; then
	for cfg in "$DIR/sites/common_site_config.json" "$DIR"/sites/*/site_config.json; do
		[ -f "$cfg" ] || continue
		if [ "$(pyhelp conf-flag "$cfg" tex_production)" = 1 ]; then
			die "$cfg sets tex_production (a live site); this local-testing script refuses to touch this bench"
		fi
	done
fi

# ---------------------------------------------------------------- 1. bench
step "Frappe bench ($FRAPPE_BRANCH)"
if [ "$NEED_INIT" = 0 ]; then
	skip "bench exists at $DIR (Frappe $(env_py -c 'import frappe; print(frappe.__version__)' 2>/dev/null || echo '?'))"
else
	[ ! -e "$DIR" ] || die "$DIR exists but is not a complete bench (left over from a failed run?). Remove it (rm -rf '$DIR') or choose another --dir."
	init_args=(init --frappe-branch "$FRAPPE_BRANCH" --python "$PY" --no-backups --skip-assets)
	if [ "$REDIS" != bench ]; then init_args+=(--skip-redis-config-generation); fi
	# "y": if init fails, let bench roll back (delete) the half-made directory
	(cd "$(dirname "$DIR")" && printf 'y\n' | "$BENCH" "${init_args[@]}" "$(basename "$DIR")") ||
		die "bench init failed - see the output above, fix the cause and re-run"
	bench_complete || die "bench init did not finish - see the output above, fix the cause and re-run"
	ok "bench created (Frappe $(env_py -c 'import frappe; print(frappe.__version__)'))"
fi

# ---------------------------------------------------------------- 2. configuration
step "Bench configuration and Procfile"
if [ "$REDIS" = bench ]; then
	R_CACHE="redis://127.0.0.1:$REDIS_CACHE_PORT"
	R_QUEUE="redis://127.0.0.1:$REDIS_QUEUE_PORT"
else
	R_CACHE=$REDIS
	R_QUEUE=$REDIS
fi
pyhelp json-set "$DIR/sites/common_site_config.json" \
	"db_host=$DB_HOST" "db_port:=$DB_PORT" "webserver_port:=$PORT" "socketio_port:=$SOCKETIO_PORT" \
	"file_watcher_port:=$FILE_WATCHER_PORT" "redis_cache=$R_CACHE" "redis_queue=$R_QUEUE" "redis_socketio=$R_CACHE"
if [ "$REDIS" = bench ]; then
	bench_in setup redis >/dev/null || die "bench setup redis failed"
fi
mkdir -p "$DIR/tex-local"

# Frappe's dev web server (`bench serve`) always listens on 0.0.0.0, every network
# interface, with the Werkzeug debugger on. This wrapper runs the same command
# bound to TEX_BIND instead.
cat >"$DIR/tex-local/serve.py" <<'EOF'
"""Generated by TEX Engine deploy/tex-local/setup-local.sh - re-run the script instead of editing.

Runs Frappe's development web server exactly like `bench serve`, but listening on
TEX_BIND (default 127.0.0.1, this computer only) instead of 0.0.0.0 (every network
interface). Run from the bench's sites/ directory:

    TEX_BIND=127.0.0.1 ../env/bin/python ../tex-local/serve.py frappe serve --port 8000
"""

import os
import warnings

import werkzeug.serving

_run_simple = werkzeug.serving.run_simple
_host = os.environ.get("TEX_BIND") or "127.0.0.1"


def _run_simple_bound(hostname, port, application, *args, **kwargs):
	return _run_simple(_host, port, application, *args, **kwargs)


werkzeug.serving.run_simple = _run_simple_bound

if __name__ == "__main__":
	import frappe
	from frappe.utils.bench_helper import main

	if not frappe._dev_server:
		warnings.simplefilter("ignore")
	main()
EOF
cat >"$DIR/tex-local/bind.js" <<'EOF'
// Generated by TEX Engine deploy/tex-local/setup-local.sh - re-run the script instead of editing.
// Preloaded (node --require) in front of apps/frappe/socketio.js so Frappe's realtime
// server listens on TEX_BIND (default 127.0.0.1) instead of every network interface.
// Its start-up line still prints "ws://0.0.0.0:<port>"; that text is hard-coded.
"use strict";
const net = require("net");
const host = process.env.TEX_BIND || "127.0.0.1";
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
	const first = args[0];
	const isPort = typeof first === "number" || (typeof first === "string" && /^\d+$/.test(first));
	if (isPort && typeof args[1] !== "string") args.splice(1, 0, host);
	return listen.apply(this, args);
};
EOF
WORKER_ENV=''
if [ "$OS" = mac ]; then WORKER_ENV='OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES NO_PROXY=* '; fi
{
	echo "# Generated by TEX Engine deploy/tex-local/setup-local.sh - re-run the script to change it"
	echo "# (\`bench setup procfile\` would replace it with Frappe's default, which listens on 0.0.0.0)."
	if [ "$REDIS" = bench ]; then
		echo "redis_cache: redis-server config/redis_cache.conf"
		echo "redis_queue: redis-server config/redis_queue.conf"
	fi
	echo "web: cd sites && TEX_BIND=$BIND exec ../env/bin/python ../tex-local/serve.py frappe serve --port $PORT"
	echo "socketio: TEX_BIND=$BIND exec node --require ./tex-local/bind.js apps/frappe/socketio.js"
	echo "schedule: bench schedule"
	# two workers: the PMS outbox runs on the long queue, never ahead of the holds and payments (LO-08)
	echo "worker: ${WORKER_ENV}bench worker --queue short,default 1>> logs/worker.log 2>> logs/worker.error.log"
	echo "worker_long: ${WORKER_ENV}bench worker --queue long 1>> logs/worker_long.log 2>> logs/worker_long.error.log"
} >"$DIR/Procfile"
{
	echo "# Written by setup-local.sh: the choices of the last run, reused when an option is not given."
	echo "SITE=$SITE"
	echo "PORT=$PORT"
	echo "BIND=$BIND"
	echo "REDIS=$REDIS"
	echo "DB_HOST=$DB_HOST"
	echo "DB_PORT=$DB_PORT"
	echo "TIME_ZONE=$TIME_ZONE"
} >"$SETTINGS"
if [ "$REDIS" = bench ]; then cfg_redis="private $REDIS_QUEUE_PORT+$REDIS_CACHE_PORT"; else cfg_redis=$REDIS; fi
ok "ports web $PORT / realtime $SOCKETIO_PORT, Redis $cfg_redis, listening on $BIND"

ensure_listed() { # app -> make sure sites/apps.txt names it
	local f="$DIR/sites/apps.txt"
	if ! grep -qx "$1" "$f" 2>/dev/null; then
		if [ -s "$f" ] && [ -n "$(tail -c 1 "$f")" ]; then echo >>"$f"; fi
		echo "$1" >>"$f"
	fi
}
installed_from() { # module -> directory the bench env imports it from (empty when missing)
	env_py -c 'import importlib.util, os, sys
s = importlib.util.find_spec(sys.argv[1])
print(os.path.dirname(os.path.dirname(os.path.realpath(s.origin))) if s and s.origin else "")' "$1" 2>/dev/null || true
}

# ---------------------------------------------------------------- 3. payments
step "payments app ($PAYMENTS_BRANCH)"
if [ -f "$DIR/apps/payments/payments/__init__.py" ]; then
	if [ -z "$(installed_from payments)" ]; then
		uv pip install --python "$DIR/env/bin/python" -e "$DIR/apps/payments" || die "installing payments into the bench env failed"
	fi
	ensure_listed payments
	pay_head=$(git -C "$DIR/apps/payments" rev-parse HEAD 2>/dev/null || echo '?')
	if [ -n "$PAYMENTS_REF" ] && [ "$pay_head" != "$PAYMENTS_REF" ]; then
		info "note: apps/payments is at $pay_head, not at the verified $PAYMENTS_REF; keeping it"
	fi
	skip "apps/payments exists ($(printf '%.7s' "$pay_head"))"
else
	# a full git URL: short names make bench query api.github.com
	bench_in get-app --branch "$PAYMENTS_BRANCH" --skip-assets "$PAYMENTS_URL" </dev/null ||
		die "bench get-app payments failed - see the output above"
	[ -f "$DIR/apps/payments/payments/__init__.py" ] || die "bench get-app did not create apps/payments"
	if [ -n "$PAYMENTS_REF" ] && [ "$(git -C "$DIR/apps/payments" rev-parse HEAD)" != "$PAYMENTS_REF" ]; then
		# the verified commit (develop moves); --branch cannot take a commit, so check it out
		{ git -C "$DIR/apps/payments" fetch --quiet --depth 1 "$PAYMENTS_URL" "$PAYMENTS_REF" &&
			git -C "$DIR/apps/payments" checkout --quiet --detach FETCH_HEAD; } ||
			die "could not check out payments $PAYMENTS_REF - see the output above (TEX_PAYMENTS_REF= uses the tip of $PAYMENTS_BRANCH instead)"
		uv pip install --python "$DIR/env/bin/python" -e "$DIR/apps/payments" || die "installing payments into the bench env failed"
	fi
	ensure_listed payments
	ok "payments $(git -C "$DIR/apps/payments" rev-parse --short HEAD 2>/dev/null || true)"
fi

# ---------------------------------------------------------------- 4. kamra (this repo)
step "kamra app (your checkout, linked)"
KAMRA_LINK="$DIR/apps/kamra"
kamra_msg=''
if [ -L "$KAMRA_LINK" ]; then
	cur=$(cd "$KAMRA_LINK" 2>/dev/null && pwd -P || true)
	if [ "$cur" != "$REPO" ]; then
		if [ "$REPO_EXPLICIT" = 1 ] || [ -z "$cur" ]; then
			ln -sfn "$REPO" "$KAMRA_LINK"
			kamra_msg="re-linked (was ${cur:-a broken link})"
		else
			warn "apps/kamra points to $cur, not to $REPO; keeping it (pass --repo to change)"
			REPO=$cur
		fi
	fi
elif [ -e "$KAMRA_LINK" ]; then
	warn "apps/kamra is a directory, not a link to your checkout; using it as it is"
	REPO=$(cd "$KAMRA_LINK" && pwd -P)
else
	ln -s "$REPO" "$KAMRA_LINK"
	kamra_msg="linked"
fi
if [ "$(installed_from kamra)" != "$REPO" ]; then
	uv pip install --python "$DIR/env/bin/python" -e "$REPO" || die "installing kamra (editable) into the bench env failed"
	kamra_msg="${kamra_msg:+$kamra_msg, }installed (editable)"
fi
ensure_listed kamra
if [ -n "$kamra_msg" ]; then ok "apps/kamra -> $REPO: $kamra_msg"; else skip "apps/kamra -> $REPO, installed (editable)"; fi

# ---------------------------------------------------------------- 5. redis for setup
step "Redis for the setup steps"
if [ "$REDIS" = bench ]; then
	for kind in queue cache; do
		if [ "$kind" = queue ]; then rp=$REDIS_QUEUE_PORT; else rp=$REDIS_CACHE_PORT; fi
		if pyhelp redis-ping 127.0.0.1 "$rp"; then
			rdir=$(pyhelp redis-dir 127.0.0.1 "$rp" 2>/dev/null || true)
			case "$rdir" in
			"$DIR/config/pids" | "$DIR"/config/pids/) info "Redis $kind on :$rp is this bench's (already running)" ;;
			*) die "port $rp is used by another Redis (${rdir:-unknown}); choose another --port" ;;
			esac
		elif pyhelp port-open 127.0.0.1 "$rp"; then
			die "port $rp is used by another program; choose another --port"
		else
			(cd "$DIR" && redis-server "config/redis_$kind.conf" --daemonize yes >/dev/null)
			STARTED_REDIS="$STARTED_REDIS $kind"
			i=0
			until pyhelp redis-ping 127.0.0.1 "$rp"; do
				i=$((i + 1))
				[ $i -lt 50 ] || die "the private Redis ($kind) did not start on port $rp"
				sleep 0.2
			done
		fi
	done
	redis_note=''
	if [ -n "$STARTED_REDIS" ]; then redis_note=' (started for setup, stopped again at the end)'; fi
	ok "private Redis on 127.0.0.1:$REDIS_QUEUE_PORT and :$REDIS_CACHE_PORT$redis_note"
else
	out=$(pyhelp redis-ping-url "$REDIS" 2>&1) || die "cannot reach Redis at $REDIS: $out"
	ok "Redis at $REDIS answers"
fi

# ---------------------------------------------------------------- 6. site
step "Site $SITE"
# (a bench with a tex_production site was refused before any change)
SITE_PREEXISTED=0
if [ "$RESET" = 1 ]; then
	confirm "--reset: DROP site $SITE and its database (a backup is kept under $DIR/archived/sites) and create it again?" ||
		die "--reset needs confirmation (answer y, or add --yes)"
	if site_exists; then
		(
			# shellcheck disable=SC2030 # exported to this subshell only, on purpose
			export TEX_LOCAL_DB_ROOT_PW="$DB_ROOT_PASSWORD"
			frappe_cli drop-site "$SITE" --db-root-username root --db-root-password @env:TEX_LOCAL_DB_ROOT_PW --force </dev/null
		) || die "bench drop-site failed - see the output above"
		info "dropped $SITE"
	fi
fi
if site_exists; then
	SITE_PREEXISTED=1
	skip "site exists (use --reset to start over)"
else
	force=''
	if [ -e "$DIR/sites/$SITE" ]; then
		[ "$RESET" = 1 ] || die "$DIR/sites/$SITE exists without a site_config.json (a failed earlier run?). Re-run with --reset."
		force=--force
	fi
	(
		# shellcheck disable=SC2031 # exported to this subshell only, on purpose
		export TEX_LOCAL_DB_ROOT_PW="$DB_ROOT_PASSWORD" TEX_LOCAL_ADMIN_PW="$ADMIN_PASSWORD"
		frappe_cli new-site "$SITE" --db-root-username root --db-root-password @env:TEX_LOCAL_DB_ROOT_PW \
			--admin-password @env:TEX_LOCAL_ADMIN_PW ${force:+"$force"} </dev/null
	) || die "bench new-site failed - see the output above"
	site_exists || die "bench new-site did not create $SITE"
	ok "site created (Administrator password: $([ "$ADMIN_PASSWORD" = "$DEFAULT_ADMIN_PASSWORD" ] && echo "$DEFAULT_ADMIN_PASSWORD" || echo 'the one you gave'))"
fi

site_probe() { # -> key=value lines about the site; fails when it cannot be opened
	(cd "$DIR/sites" && "$DIR/env/bin/python" - "$SITE" 2>"$TMPD/probe.err" <<'EOF'
import sys

import frappe

frappe.init(sys.argv[1], sites_path=".")
frappe.connect()
try:
	apps = frappe.get_installed_apps()
	print("apps=" + ",".join(apps))
	# the seed finished: booking site, demo users and its bookings exist (a failed seed is simply run again)
	seeded = ("kamra" in apps and frappe.db.table_exists("TEX Booking Site")
	          and bool(frappe.db.exists("TEX Booking Site", "aurora"))
	          and bool(frappe.db.exists("User", "revenue@demo.tex"))
	          and frappe.db.count("TEX Booking", {"booking_site": "aurora"}) > 0)
	print("seeded=%d" % int(bool(seeded)))
	print("scheduler=%d" % int(frappe.db.get_single_value("System Settings", "enable_scheduler") or 0))
	print("tz=%s" % (frappe.db.get_single_value("System Settings", "time_zone") or ""))
finally:
	frappe.destroy()
EOF
	)
}
probe_val() { printf '%s\n' "$PROBE" | sed -n "s/^$1=//p" | tail -n 1; }
PROBE=$(site_probe) || {
	tail -n 5 "$TMPD/probe.err" >&2
	die "cannot open site $SITE (database missing or MariaDB down?). Check MariaDB, or start over with --reset."
}

# ---------------------------------------------------------------- 7. apps on the site
step "Apps on the site"
# a `bench new-site` that crashed half-way leaves a site_config.json behind, but Frappe
# itself is then missing from the site's installed apps
case ",$(probe_val apps)," in
*",frappe,"*) ;;
*) die "site $SITE was not created completely (an earlier run stopped while creating it; Frappe itself is not installed on it). Start over with --reset." ;;
esac
done_apps=''
for app in payments kamra; do
	case ",$(probe_val apps)," in
	*",$app,"*) ;;
	*)
		bench_in --site "$SITE" install-app "$app" </dev/null || die "installing $app on $SITE failed - see the output above"
		done_apps="$done_apps $app"
		;;
	esac
done
if [ -n "$done_apps" ]; then
	PROBE=$(site_probe) || die "cannot open site $SITE after installing apps"
	ok "installed:$done_apps"
else
	skip "payments and kamra already installed"
fi

# ---------------------------------------------------------------- 7b. migrate (re-runs)
step "Migrate"
if [ "$SITE_PREEXISTED" = 1 ] && [ -z "$done_apps" ]; then
	# after a git pull: new DocTypes and patches of the checkout (and payments)
	bench_in --site "$SITE" migrate </dev/null || die "bench migrate failed - see the output above"
	ok "site migrated (new DocTypes and patches applied)"
else
	skip "site just created or its apps just installed; nothing to migrate"
fi

# ---------------------------------------------------------------- 8. site settings
step "Site settings"
pyhelp json-set "$DIR/sites/$SITE/site_config.json" \
	"developer_mode:=1" "allow_tests:=true" "tex_public_search_limit:=1000" "tex_public_write_limit:=1000"
# TEX signs offer keys and payment return URLs with the site's encryption_key (G-89) and
# never falls back; a fresh Frappe site only gets one lazily, so create it now with
# Frappe's own generator (a no-op when the site already has one).
ensure_encryption_key() {
	(cd "$DIR/sites" && "$DIR/env/bin/python" - "$SITE" <<'EOF'
import sys

import frappe

frappe.init(sys.argv[1], sites_path=".")
try:
	had = bool(frappe.local.conf.get("encryption_key"))
	from frappe.utils.password import get_encryption_key

	get_encryption_key()
	print("encryption_key present" if had else "encryption_key created")
finally:
	frappe.destroy()
EOF
	)
}
key_msg=$(ensure_encryption_key) || die "could not ensure the site's encryption_key"
bench_in use "$SITE" >/dev/null
sched_msg='scheduler already enabled'
if [ "$(probe_val scheduler)" != 1 ]; then
	bench_in --site "$SITE" enable-scheduler </dev/null >/dev/null || die "enabling the scheduler failed"
	sched_msg='scheduler enabled'
fi
ok "developer_mode=1, allow_tests, public API limits 1000/min, $key_msg, default site $SITE, $sched_msg"

# ---------------------------------------------------------------- 9. demo data
step "TEX demo data"
SITE_TZ=$(probe_val tz)
if [ "$(probe_val seeded)" = 1 ]; then
	if [ "$TZ_EXPLICIT" = 1 ] && [ "$SITE_TZ" != "$TIME_ZONE" ]; then
		warn "--time-zone $TIME_ZONE not applied: the time zone is set only when the demo data is loaded, and this site already has it (on ${SITE_TZ:-?}). To start over on $TIME_ZONE, re-run with --reset."
	fi
	skip "demo data present (booking site '$DEMO_SLUG'), time zone ${SITE_TZ:-?}; not seeding again"
else
	# Time zone BEFORE the demo data. Frappe stores times without a zone: contract versions
	# are stamped with the site's local time when published, and a later switch to a zone
	# further west would make them "not yet effective" for hours (no offers). The first
	# hotel of a site also copies its own zone (Kamra's default, Asia/Kolkata) into System
	# Settings, so while the demo data is loaded TIME_ZONE is made the hotels' default (a
	# Property Setter that is removed again right after).
	set_site_tz() {
		bench_in --site "$SITE" execute frappe.db.set_single_value \
			--args "$(pyhelp json-list "System Settings" time_zone "$TIME_ZONE")" </dev/null >/dev/null
	}
	set_site_tz || die "setting the site time zone failed - see the output above"
	bench_in --site "$SITE" execute frappe.custom.doctype.property_setter.property_setter.make_property_setter \
		--args "$(pyhelp json-list Property timezone default "$TIME_ZONE" Data)" </dev/null >/dev/null ||
		die "setting the demo hotels' time zone failed - see the output above"
	bench_in --site "$SITE" clear-cache </dev/null || die "bench clear-cache failed"
	# the password travels in the environment, not on the command line
	(
		export TEX_LOCAL_DEMO_PW="$DEMO_PASSWORD"
		bench_in --site "$SITE" execute kamra.tex.devtools.demo_seed.execute \
			--kwargs "{'password': __import__('os').environ['TEX_LOCAL_DEMO_PW']}" </dev/null
	) || die "loading the demo data failed - see the output above (re-running the script retries it; the seed is idempotent)"
	bench_in --site "$SITE" execute frappe.custom.doctype.property_setter.property_setter.delete_property_setter \
		--args "$(pyhelp json-list Property default timezone)" </dev/null >/dev/null ||
		die "removing the temporary Property Setter failed - see the output above"
	set_site_tz || die "setting the site time zone failed - see the output above"
	bench_in --site "$SITE" clear-cache </dev/null || die "bench clear-cache failed"
	ok "demo data seeded, time zone $TIME_ZONE (site and demo hotels)"
fi

# ---------------------------------------------------------------- 10. assets
step "Frappe and payments assets"
assets_ok() {
	grep -q '"desk.bundle.js"' "$DIR/sites/assets/assets.json" 2>/dev/null &&
		[ -e "$DIR/sites/assets/frappe" ] && [ -e "$DIR/sites/assets/payments" ] &&
		[ -e "$DIR/sites/assets/kamra/tex" ] &&
		[ "$(cd "$DIR/sites/assets/kamra" 2>/dev/null && pwd -P)" = "$REPO/kamra/public" ]
}
if assets_ok; then
	skip "built (rebuild after updating Frappe: bench build --apps frappe,payments)"
else
	# kamra's staff SPA and booking engine bundles are committed in kamra/public;
	# only Frappe's and payments' own assets are built. (Building kamra would run its
	# npm build and rewrite those committed bundles.)
	bench_in build --apps frappe,payments </dev/null || die "bench build failed - see the output above"
	assets_ok || die "assets are incomplete after bench build - see the output above"
	ok "built frappe and payments; kamra's committed bundles linked"
fi

# ---------------------------------------------------------------- summary
stop_setup_redis
TOTAL=$(($(date +%s) - T_START))
URL="http://localhost:$PORT"
[ "$BIND" = 127.0.0.1 ] || [ "$BIND" = 0.0.0.0 ] || URL="http://$BIND:$PORT"
if [ "$DEMO_PASSWORD" = "$DEFAULT_DEMO_PASSWORD" ]; then DEMO_SHOWN=$DEFAULT_DEMO_PASSWORD; else DEMO_SHOWN='(the --demo-password you chose)'; fi
if [ "$ADMIN_PASSWORD" = "$DEFAULT_ADMIN_PASSWORD" ]; then ADMIN_SHOWN=$DEFAULT_ADMIN_PASSWORD; else ADMIN_SHOWN='(the --admin-password you chose)'; fi
if [ "$BIND" = 127.0.0.1 ]; then
	LISTEN_NOTE='(this computer only)'
else
	LISTEN_NOTE='- reachable from your network: change the passwords'
fi

printf '\n%sSteps%s\n%s' "$C_B" "$C_N" "$TIMINGS"
printf '  total %ss\n' "$TOTAL"
cat <<EOF

${C_G}${C_B}TEX Engine local bench is ready.${C_N}  ${C_Y}LOCAL TESTING ONLY - these passwords are public defaults.${C_N}

Start it (Ctrl+C stops everything; nothing runs until you do this):
    cd $DIR && bench start
EOF
if [ "$BENCH_ON_PATH" = 0 ]; then
	cat <<EOF
    (bench is not on your PATH yet: run 'uv tool update-shell' and open a new terminal,
     or: export PATH="$(dirname "$BENCH"):\$PATH")
EOF
fi
cat <<EOF

Then open:
    Staff app (TEX)      $URL/kamra/tex
    Booking engine       $URL/book/$DEMO_SLUG
    Frappe Desk (admin)  $URL/desk
    (the same site also answers on http://$SITE:$PORT - browsers resolve *.localhost)

Logins:
    Administrator        $ADMIN_SHOWN
    revenue@demo.tex     $DEMO_SHOWN   revenue manager, hotel group
    agent@demo.tex       $DEMO_SHOWN   call-centre / reservations agent
    finance@demo.tex     $DEMO_SHOWN   finance
    beach.gm@demo.tex    $DEMO_SHOWN   hotel admin, Aurora Beach Resort only

Listening on $BIND $LISTEN_NOTE
Re-run this script any time: finished steps are skipped. Start over: add --reset.
Guide: deploy/tex-local/NATIVE.md
EOF
