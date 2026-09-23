#!/usr/bin/env bash
# TEX Engine - local test container entrypoint (see deploy/tex-local/README.md).
#
# First start (no finished site yet): configure the bench for the compose services,
# create the site, install payments + kamra, apply local-test settings and load the
# demo data. Later starts: `bench migrate` only - data is kept and nothing is re-seeded.
# Then run web + scheduler + worker in the foreground (honcho).
#
# LOCAL TESTING ONLY: developer_mode is on and the demo passwords are well known.
set -Eeuo pipefail

BENCH_DIR=/home/frappe/frappe-bench
SITE="${TEX_SITE:-tex.localhost}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-3306}"
REDIS_URL="${REDIS_URL:-redis://redis:6379}"
TIME_ZONE="${TEX_TIME_ZONE:-Europe/Istanbul}"
PORT_HINT="${TEX_PORT:-8000}"

INSTALLED_MARKER="sites/${SITE}/.tex-local-installed"
SEEDED_MARKER="sites/${SITE}/.tex-local-seeded"
# the site this sites volume was set up for (TEX_SITE of the first start)
SITE_RECORD="sites/.tex-local-site"

log() { printf '[tex-local] %s\n' "$*"; }
fail() { printf '[tex-local] ERROR: %s\n' "$*" >&2; exit 1; }

hostport() { # "redis://host:port/0" -> "host port"
	local rest="${1#*://}"
	rest="${rest%%/*}"
	printf '%s %s\n' "${rest%%:*}" "${rest##*:}"
}

wait_for() { # host port label
	local host="$1" port="$2" label="$3" i
	for i in $(seq 1 90); do
		if (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null; then
			return 0
		fi
		[ "$i" = 1 ] && log "waiting for ${label} at ${host}:${port} ..."
		sleep 2
	done
	fail "${label} is not reachable at ${host}:${port} after 3 minutes"
}

json_list() { # args -> JSON list of strings (a valid Python literal for bench execute --args)
	/usr/local/bin/python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@"
}

set_time_zone() { # System Settings time zone of the site
	bench --site "$SITE" execute frappe.db.set_single_value \
		--args "$(json_list "System Settings" time_zone "$TIME_ZONE")"
}

# Frappe commands that take a password. `bench ...` would write the whole command line,
# passwords included, to logs/bench.log; frappe_cli.py runs the same Frappe command and
# replaces "@env:NAME" arguments with the environment variable NAME.
frappe_cli() {
	(cd "${BENCH_DIR}/sites" && ../env/bin/python /opt/tex-local/frappe_cli.py "$@")
}

step() { # label, command...
	local label="$1" started=$SECONDS
	shift
	log "${label} ..."
	"$@"
	log "${label}: done in $((SECONDS - started)) s"
}

cd "$BENCH_DIR"

# --- every start: point the (volume-backed) sites dir at this image and the services ---
if [ ! -L sites/assets ]; then
	rm -rf sites/assets
	ln -s "${BENCH_DIR}/assets" sites/assets
fi
printf 'frappe\npayments\nkamra\n' > sites/apps.txt
[ -s sites/common_site_config.json ] || echo '{}' > sites/common_site_config.json
bench set-config -g db_host "$DB_HOST" >/dev/null
if [ "$DB_PORT" != "3306" ]; then bench set-config -g -p db_port "$DB_PORT" >/dev/null; fi
for key in redis_cache redis_queue redis_socketio; do
	bench set-config -g "$key" "$REDIS_URL" >/dev/null
done

wait_for "$DB_HOST" "$DB_PORT" "MariaDB"
# shellcheck disable=SC2046
wait_for $(hostport "$REDIS_URL") "Redis"

# TEX_SITE is fixed by the first start: a different name later would quietly create and
# seed a second site and make it the default.
if [ -s "$SITE_RECORD" ]; then
	first_site="$(cat "$SITE_RECORD")"
	if [ "$first_site" != "$SITE" ] && [ -f "sites/${first_site}/.tex-local-installed" ]; then
		fail "TEX_SITE is '${SITE}', but this installation was created with TEX_SITE='${first_site}'. Set TEX_SITE=${first_site} again (in .env), or start from scratch with: docker compose down -v && docker compose up -d"
	fi
fi

if [ -f "$SEEDED_MARKER" ]; then
	# --- later starts: keep everything, only apply schema/patch updates of the image ---
	trap 'printf "\n[tex-local] ERROR: bench migrate failed for site %s (see the messages above).\n[tex-local] If the database volume was removed but the sites volume kept, or the data is not needed, start from scratch:\n[tex-local]     docker compose down -v && docker compose up -d\n" "$SITE" >&2' ERR
	step "Migrating site ${SITE} (existing data kept, demo data not re-seeded)" \
		bench --site "$SITE" migrate
	trap - ERR
else
	# --- first start (or a first start that stopped half-way) ---
	started_first=$SECONDS
	trap 'printf "\n[tex-local] ERROR: the first start failed (see the messages above).\n[tex-local] Restarting the container resumes it; to start from scratch run:\n[tex-local]     docker compose down -v && docker compose up -d\n" >&2' ERR
	: "${DB_ROOT_PASSWORD:?DB_ROOT_PASSWORD must be set for the first start}"
	: "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set for the first start}"
	: "${DEMO_PASSWORD:?DEMO_PASSWORD must be set for the first start}"
	/usr/local/bin/python3 -c 'import sys, zoneinfo; zoneinfo.ZoneInfo(sys.argv[1])' "$TIME_ZONE" \
		|| fail "TEX_TIME_ZONE=${TIME_ZONE} is not a valid IANA time zone"

	if [ ! -f "$INSTALLED_MARKER" ]; then
		printf '%s\n' "$SITE" > "$SITE_RECORD"
		if [ -d "sites/${SITE}" ]; then
			log "Site ${SITE} exists but its installation did not finish - dropping it and starting over"
			frappe_cli drop-site "$SITE" --db-root-password @env:DB_ROOT_PASSWORD --no-backup --force || true
			rm -rf "sites/${SITE}"
		fi
		step "Creating site ${SITE}" \
			frappe_cli new-site "$SITE" --db-root-password @env:DB_ROOT_PASSWORD \
			--admin-password @env:ADMIN_PASSWORD --mariadb-user-host-login-scope='%'
		step "Installing app payments" bench --site "$SITE" install-app payments
		step "Installing app kamra (TEX Engine)" bench --site "$SITE" install-app kamra
		touch "$INSTALLED_MARKER"
	fi

	log "Applying local-test settings (encryption key, developer_mode, public API rate limits, default site, scheduler)"
	# TEX signs offers and payment callbacks with the site's encryption_key (ADR-041) and
	# refuses to work without one; Frappe only creates it lazily. Generate it now if it
	# is missing (stdout discarded: the command prints the key).
	bench --site "$SITE" execute frappe.utils.password.get_encryption_key >/dev/null
	bench --site "$SITE" set-config -p developer_mode 1
	bench --site "$SITE" set-config -p tex_public_write_limit 1000
	bench --site "$SITE" set-config -p tex_public_search_limit 1000
	bench use "$SITE"
	bench --site "$SITE" enable-scheduler

	# Time zone BEFORE the demo data: contract versions are stamped with the site's local
	# time when published, and a later time zone change would shift "now" behind those
	# stamps (no contract sells until the clocks catch up). The first hotel a site gets
	# also copies its own time zone (Kamra default: Asia/Kolkata) into System Settings, so
	# the demo hotels are created with TEX_TIME_ZONE as that default (a Property Setter
	# that exists only while the demo data is loaded).
	log "Setting the site time zone to ${TIME_ZONE} (System Settings and the demo hotels)"
	set_time_zone
	bench --site "$SITE" execute frappe.custom.doctype.property_setter.property_setter.make_property_setter \
		--args "$(json_list Property timezone default "$TIME_ZONE" Data)" >/dev/null
	bench --site "$SITE" clear-cache

	# the demo password is read from the environment inside the command, so it is neither
	# on the command line nor in logs/bench.log
	step "Loading demo data (kamra.tex.devtools.demo_seed)" \
		bench --site "$SITE" execute kamra.tex.devtools.demo_seed.execute \
		--kwargs "{'password': __import__('os').environ['DEMO_PASSWORD']}"

	bench --site "$SITE" execute frappe.custom.doctype.property_setter.property_setter.delete_property_setter \
		--args "$(json_list Property default timezone)"
	set_time_zone
	bench --site "$SITE" clear-cache
	touch "$SEEDED_MARKER"
	trap - ERR
	log "First start finished in $((SECONDS - started_first)) s"
fi

cat <<EOF
[tex-local] ------------------------------------------------------------------
[tex-local] TEX Engine (local test) is starting on http://localhost:${PORT_HINT}
[tex-local]   staff app      http://localhost:${PORT_HINT}/kamra/tex
[tex-local]   booking engine http://localhost:${PORT_HINT}/book/aurora
[tex-local]   users revenue@demo.tex, agent@demo.tex, finance@demo.tex, beach.gm@demo.tex
[tex-local]         password = DEMO_PASSWORD from .env (default TexDemo#2026)
[tex-local]   Frappe desk    http://localhost:${PORT_HINT}/desk (Administrator / ADMIN_PASSWORD)
[tex-local] Local testing only - do not expose this container to a network.
[tex-local] ------------------------------------------------------------------
EOF

exec honcho start --no-colour -f /opt/tex-local/Procfile -d "$BENCH_DIR"
