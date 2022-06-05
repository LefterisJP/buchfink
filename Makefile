all: lint typecheck test

lint:
	pylint buchfink
	pycodestyle buchfink tests/*.py

typecheck:
	mypy buchfink tests/*.py

test:
	py.test

test-local:
	py.test -m 'not blockchain_data'

test-remote:
	py.test -m 'blockchain_data'
