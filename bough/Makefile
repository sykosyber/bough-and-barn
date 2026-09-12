.PHONY: test install bits ontology machine c2

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest -q

bits:
	python3 -m bough bits -n 4

ontology:
	python3 -m bough ontology --copies 1

machine:
	python3 -m bough machine

c2:
	python3 -m bough c2
