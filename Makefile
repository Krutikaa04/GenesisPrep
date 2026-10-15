PY ?= python

build:
	docker build -t deadbits .

test:
	$(PY) -m unittest discover -s tests -p "test_*.py"

reference:
	$(PY) tools/compare_expected.py

run:
	$(PY) -m deadbits.cli samples/official/samples out
