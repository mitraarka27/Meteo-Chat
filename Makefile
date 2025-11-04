.PHONY: venv install run run-all fmt lint build clean

venv:
	python -m venv .venv

install: venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e .

run:
	. .venv/bin/activate && meteo-chat-app

run-all:
	. .venv/bin/activate && meteo-chat

fmt:
	. .venv/bin/activate && pip install ruff && ruff format .

lint:
	. .venv/bin/activate && pip install ruff && ruff check .

build:
	. .venv/bin/activate && pip install build && python -m build

clean:
	rm -rf .venv dist build *.egg-info