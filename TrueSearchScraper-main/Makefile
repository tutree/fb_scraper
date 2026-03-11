export DOCKER_REPO=skamirik/true-search-scraper

.PHONY: all build

all: build

build:
	$(eval TAG := $(shell date -u +%s))
	docker build -t "${DOCKER_REPO}:${TAG}" .

push:
	$(eval TAG := $(shell date -u +%s))
	docker build -t "${DOCKER_REPO}:${TAG}" .
	docker push "${DOCKER_REPO}:${TAG}"

run-name-search:
	$(eval TAG := $(shell date -u +%s))
	docker build -t "${DOCKER_REPO}:${TAG}" .
	docker run --rm -it --env-file ./.env \
		${DOCKER_REPO}:${TAG} yarn start:search-by-name \
			--sheetId ${SHEET_ID} --tabName ${TAB_NAME} --queueName ${TAB_NAME}

run-worker:
	$(eval TAG := $(shell date -u +%s))
	docker build -t "${DOCKER_REPO}:${TAG}" .
	docker run --rm -it --env-file ./.env \
		${DOCKER_REPO}:${TAG} yarn start:worker --queueName TRUE_SEARCH_TARGETS
