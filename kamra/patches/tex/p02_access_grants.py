"""TEX T4: make existing property access explicit, then enable strict tenancy.

Once, at the upgrade (G-76): a forced re-run finds the patch logged and changes nothing. Since the
upgrade, access comes from grants only, so a user added later has none until one is granted; a
re-run must never give such a user every hotel as the legacy "no restriction" did."""


def execute():
	from kamra.tex import setup

	if setup.ran_before(__name__):
		return
	setup.migrate_legacy_access()
