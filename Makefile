all: lint typecheck test

lint:
	pylint buchfink/schema.py buchfink/account.py buchfink/serialization.py buchfink/config.py buchfink/datatypes.py buchfink/cli.py buchfink/classification.py

typecheck:
	mypy buchfink

test:
	py.test
