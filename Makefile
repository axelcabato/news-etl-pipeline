.PHONY: build up down logs test clean

build:
	docker compose build etl_app
	docker compose build dashboard

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test:
	docker compose run --rm etl_app pytest tests/

clean:
	docker compose down -v
	docker system prune -f