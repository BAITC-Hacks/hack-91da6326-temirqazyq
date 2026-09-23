.PHONY: install dev-back dev-front build run test verify

install:
	pip install -r backend/requirements.txt
	cd frontend && npm install

dev-back:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-front:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

run: build
	cd backend && uvicorn app.main:app --port 8000

test:
	cd backend && python -m pytest -q

# Независимая перепроверка математики: формула реализована заново, без импорта движка,
# и результаты сравниваются. --full добавляет полный перебор всех наборов (~10 секунд).
verify:
	python tools/selfcheck.py --full
