"""TEX T10: composite indexes for availability, restrictions and FX lookups."""


def execute():
	from kamra.tex import setup

	setup.ensure_indexes()
