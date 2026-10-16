PY ?= python
.PHONY: build test reference run evaluate variants docker-check

build:
	docker build --network=none --pull=false -t deadbits .

test:
	$(PY) -m unittest discover -s tests -p "test_*.py"

reference:
	$(PY) tools/compare_expected.py

run:
	$(PY) -m deadbits.cli samples/official/samples out

evaluate:
	$(PY) tools/evaluate.py --json evaluation.json

variants:
	$(PY) tools/make_variants.py variants

docker-check:
	SALVAGE_PYTHON="$(PY)" tools/docker_check.sh
