.PHONY: dev-up deploy test test-identity fake-zenbo smoke graph

dev-up:
	docker compose up -d --build

deploy:
	@if [ -f deploy.sh ]; then bash deploy.sh; else docker compose up -d --build; fi

test:
	cd services/core-api && pytest -q

test-identity:
	cd services/core-api && pytest -q test_db.py test_oidc.py test_speech_phrases.py test_youtube_defaults.py

fake-zenbo:
	python tools/fake_zenbo.py

smoke:
	bash scripts/smoke.sh

graph:
	graphify update .
