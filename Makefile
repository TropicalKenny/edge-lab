.PHONY: test run migrate

test:
	python -m pytest

run:
	uvicorn app.main:app --reload

migrate:
	alembic upgrade head
