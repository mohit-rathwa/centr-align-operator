.PHONY: install run test
install:
	python -m pip install -r requirements.txt
run:
	uvicorn app.main:app --app-dir backend --reload

test:
	pytest -q backend/tests
