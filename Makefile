.PHONY: setup lint test ingest sample labelstudio-up labelstudio-down tasks predict-regex score score-silver train-spacy train-transformer llm-collect mlflow-ui gold-agreement gold-finalize link predict-transformer gold-round gold-round-agreement gold-round-finalize learning-curve run-corpus run-corpus-gbert graph compare-runs db-up db-down db-load api demo report-html docker-build docker-run drift drift-series tf-init tf-plan tf-apply tf-destroy tf-validate aws-push aws-sync aws-load aws-deploy aws-smoke aws-measure aws-bootstrap

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

# --- week 3: full corpus, Postgres, citation graph, API --------------------------------------
RUN ?= regex-v0.4
GBERT_MODEL ?= models/gbert-base-b13-s0-ner

run-corpus:  ## regex + linking over the whole corpus under Dask -> data/runs/$(RUN)/
	uv run caselaw run-corpus --name $(RUN) --extractor regex

run-corpus-gbert:  ## the 260-decision gbert model over the whole corpus on the GPU -> data/runs/gbert-b13-s0/
	TOKENIZERS_PARALLELISM=false uv run caselaw run-corpus --name gbert-b13-s0 --extractor gbert --model-dir $(GBERT_MODEL)

graph:  ## citation graph, centrality table, graph.html and the three analyses of a run
	uv run caselaw graph --run $(RUN)

compare-runs:  ## usage: make compare-runs A=regex-v0.4 B=gbert-b13-s0
	uv run caselaw compare-runs $(A) $(B)

db-up:
	docker compose -f infra/docker-compose.yml up -d --wait

db-down:
	docker compose -f infra/docker-compose.yml down

db-load:  ## load a run into Postgres (localhost:5433, user/db caselaw)
	uv run caselaw db-load --run $(RUN)

api:  ## usage: make api BACKEND=postgres|duckdb  (http://127.0.0.1:8000/docs)
	uv run caselaw api --backend $(or $(BACKEND),duckdb) --run $(RUN)

demo:  ## the pipeline on a 100-decision sample without Postgres or cloud
	uv run caselaw demo --n 100

report-html:
	uv run python scripts/build_report_html.py

docker-build:  ## the API image (core dependencies only)
	docker build -t caselaw-api:latest .

docker-run:  ## the image against the local Postgres on :5433 (http://127.0.0.1:8000/docs)
	docker run --rm -p 8000:8000 -e CASELAW_DSN=postgresql://caselaw:caselaw@host.docker.internal:5433/caselaw caselaw-api:latest

drift:  ## usage: make drift A=2026-08 B=2026-09 [PERIOD=month|year] [RUN=regex-v0.4] [BACKEND=duckdb|postgres]
	uv run caselaw drift --a "$(A)" --b "$(B)" --period $(or $(PERIOD),month) $(if $(RUN),--run $(RUN)) $(if $(BACKEND),--backend $(BACKEND))

drift-series:  ## usage: make drift-series KIND=statute|bge|docket|code [PERIOD=month|year]
	uv run caselaw drift --series --kind $(or $(KIND),statute) --period $(or $(PERIOD),month) $(if $(RUN),--run $(RUN)) $(if $(BACKEND),--backend $(BACKEND))

# --- week 4: AWS stack (infra/terraform; validated, not applied) ---------------------------------
tf-init:      ; terraform -chdir=infra/terraform init
tf-plan:      ; terraform -chdir=infra/terraform plan
tf-apply:     ; terraform -chdir=infra/terraform apply
tf-destroy:   ; terraform -chdir=infra/terraform destroy
tf-validate:  ; terraform -chdir=infra/terraform fmt -check -recursive && terraform -chdir=infra/terraform validate
aws-push:     ; scripts/aws.sh push
aws-sync:     ; scripts/aws.sh sync $(RUN)
aws-load:     ; scripts/aws.sh load $(RUN)
aws-deploy:   ; scripts/aws.sh deploy
aws-smoke:    ; scripts/aws.sh smoke
aws-measure:  ; scripts/aws.sh measure
aws-bootstrap: ; scripts/aws.sh bootstrap $(RUN)

# --- week 4: Hetzner + Cloudflare R2 + Njalla DNS (the deployment in use) --------------------------
# Terraform credentials come from 1Password through `op run` (infra/hetzner/terraform.op.env).
hz-init:      ; scripts/hz.sh init
hz-plan:      ; scripts/hz.sh plan
hz-apply:     ; scripts/hz.sh apply
hz-destroy:   ; scripts/hz.sh destroy
hz-secrets:   ; scripts/hz.sh secrets
hz-deploy:    ; scripts/hz.sh deploy
hz-sync:      ; scripts/hz.sh sync $(RUN)
hz-load:      ; scripts/hz.sh load $(RUN)
hz-smoke:     ; scripts/hz.sh smoke
hz-measure:   ; scripts/hz.sh measure
hz-status:    ; scripts/hz.sh status
hz-ssh:       ; scripts/hz.sh ssh
hz-bootstrap: ; scripts/hz.sh bootstrap $(RUN)
