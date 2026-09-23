"""Run a Frappe command without writing secrets to logs (TEX Engine, deploy/tex-local).

`bench <command> ...` writes its whole command line to <bench>/logs/bench.log, so a
password given as an option (new-site --db-root-password / --admin-password,
drop-site --db-root-password) would be stored there in clear text. This script runs
the same Frappe command the way bench itself hands it over (frappe.utils.bench_helper,
from the bench's sites/ directory) and reads secrets from environment variables: an
argument "@env:NAME" is replaced by the value of $NAME. Nothing is logged and no
secret appears in the process list.

    cd <bench>/sites
    TEX_PW=... ../env/bin/python /path/to/frappe_cli.py --site x.localhost new-site x.localhost \\
        --db-root-password @env:TEX_PW --admin-password @env:TEX_ADMIN_PW

is the same as `bench --site x.localhost new-site x.localhost --db-root-password ...`.
Used by entrypoint.sh (Docker) and setup-local.sh (native). LOCAL TESTING ONLY.
"""

import os
import sys


def main() -> None:
	args = []
	for arg in sys.argv[1:]:
		if arg.startswith("@env:"):
			name = arg[len("@env:") :]
			value = os.environ.get(name)
			if not value:
				sys.exit(f"frappe_cli.py: environment variable {name} is empty or not set")
			arg = value
		args.append(arg)
	# bench runs: <env>/bin/python -m frappe.utils.bench_helper frappe <args> (cwd: sites/)
	sys.argv = [sys.argv[0], "frappe", *args]

	from frappe.utils.bench_helper import main as frappe_main

	frappe_main()


if __name__ == "__main__":
	main()
