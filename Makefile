.PHONY: setup lint test ingest sample labelstudio-up labelstudio-down tasks predict-regex score score-silver train-spacy train-transformer llm-collect mlflow-ui gold-agreement gold-finalize link predict-transformer gold-round gold-round-agreement gold-round-finalize learning-curve

setup:
	uv sync --all-extras

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

test:
	uv run pytest --cov=caselaw_extraction --cov-report=term-missing

ingest:
	uv run caselaw ingest

sample:
	uv run caselaw sample --n 60

tasks:
	uv run caselaw tasks

labelstudio-up:
	docker compose -f labeling/docker-compose.yml up -d

labelstudio-down:
	docker compose -f labeling/docker-compose.yml down

labelstudio-project:
	uv run python scripts/labelstudio_api.py create-project

labelstudio-import:
	uv run python scripts/labelstudio_api.py import labeling/tasks/batch1.json

labelstudio-export:
	uv run python scripts/labelstudio_api.py export > data/gold/batch1.export.json

coverage:
	uv run python scripts/regex_coverage.py

# --- week 2: extractors and scoring ---------------------------------------------------------
BATCH ?= batch2

predict-regex:
	uv run caselaw predict regex --batch $(BATCH)

score:  ## usage: make score PRED=data/pred/batch2/regex-v0.3.jsonl [NAME=run-name]
	uv run caselaw score $(PRED) --batch $(BATCH) $(if $(NAME),--name $(NAME),)

score-silver:
	uv run caselaw score silver --batch $(BATCH)

train-spacy:
	uv run caselaw train-spacy --train batch1 --eval $(BATCH) --epochs 20 --seed 0

train-transformer:
	TOKENIZERS_PARALLELISM=false uv run caselaw train-transformer --train batch1 --eval $(BATCH) --epochs 4 --seed 0

llm-collect:
	uv run python scripts/llm/collect.py $(BATCH) haiku

mlflow-ui:
	uv run mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001

gold-agreement:
	GOLD_BATCH=$(BATCH) GOLD_PASSES=a,c uv run python scripts/gold/agreement.py

gold-finalize:
	GOLD_BATCH=$(BATCH) GOLD_PASSES=a,c uv run python scripts/gold/finalize.py

# --- entity linking (the stage after any extractor) and decoding ----------------------------
link:  ## usage: make link PRED="data/pred/batch2/gbert-base-s0.jsonl data/pred/batch2/spacy-s0.jsonl"
	uv run caselaw link $(PRED) --batch $(BATCH) --log

predict-transformer:  ## usage: make predict-transformer MODEL=models/gbert-base-s0-ner DECODE=viterbi
	TOKENIZERS_PARALLELISM=false uv run caselaw predict-transformer --model-dir $(MODEL) --batch $(BATCH) --decode $(or $(DECODE),argmax)

# --- guideline v0.2 round (negative classes) over a finished batch ---------------------------
ROUND ?= v2

gold-round:  ## build labeling/tasks/<batch>.<round>.json from the batch gold + proposals (CITATIONS=--citations adds regex proposals)
	uv run python scripts/gold/make_round.py $(BATCH) $(ROUND) $(CITATIONS)

gold-round-agreement:
	GOLD_BATCH=$(BATCH) GOLD_ROUND=$(ROUND) GOLD_PASSES=a,c uv run python scripts/gold/agreement.py

gold-round-finalize:
	GOLD_BATCH=$(BATCH) GOLD_ROUND=$(ROUND) GOLD_PASSES=a,c uv run python scripts/gold/finalize.py

learning-curve:  ## usage: make learning-curve MODEL=spacy CURVE=main|extended ; then: uv run python scripts/learning_curve.py table
	TOKENIZERS_PARALLELISM=false uv run python scripts/learning_curve.py $(MODEL) $(CURVE)
