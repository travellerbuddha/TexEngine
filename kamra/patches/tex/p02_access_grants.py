"""TEX T4: make existing property access explicit, then enable strict tenancy."""


def execute():
	from kamra.tex import setup

	setup.migrate_legacy_access()
