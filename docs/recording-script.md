# Recording script (5 minutes)

One take, terminal on the left, browser on the right. Start every scene with the command
already typed. Times are targets.

| time | scene | command or view | what to say |
|---|---|---|---|
| 0:00 | the problem | `docs/report.html`, management summary | 7,999 Federal Supreme Court decisions; which statutes and precedents does the court rely on; one pipeline from text to graph to API |
| 0:30 | the gold set | Label Studio, one batch-3 decision with the nine labels | 350 decisions, two language models correcting regex proposals, adjudicated; a human check of 10 decisions found no error |
| 1:10 | the extractors | report, table 6.13 | rules against a German BERT on 260 decisions: 0.985 frozen rules, 0.993 model on held-out data; the model learns the negative classes with 150 examples each |
| 1:50 | the corpus run | `make demo` | 100 decisions through extraction, linking and the graph in two seconds, no database; the full corpus takes ten seconds on one core |
| 2:20 | the graph | report 7.3, then `data/runs/regex-v0.4/graph.html` | Art. 66 BGG in every decision; three substantiation precedents in four of ten decisions; ZPO share falling in 2025 and 2026 |
| 2:50 | rules against model | report 7.6 | Jaccard 0.97 to 0.99, identical top-20 lists; the rules go to production, the model stays for what the rules cannot read |
| 3:10 | the API | `https://api.caselaw.inat.io/docs`, `/decisions/central?limit=5`, `/decisions?bge=BGE 140 III 115&year=2026&limit=3`, one decision | same answers from Postgres and from Parquet; 5 ms per decision |
| 3:45 | the deployment | the Grafana dashboard, `make hz-deploy` in the terminal | Terraform for the server, the bucket and the DNS; Compose with secret files; the AWS variant validated and priced; one command redeploys |
| 4:20 | drift | `make drift A=2026-08 B=2026-09` | the check names September 2026: shorter decisions, more inadmissibility rulings, half the distinct articles |
| 4:45 | close | report section 10 | what is next: the GPU-served agent over the same corpus (Project 2) |

Before recording: `make db-up`, `make api BACKEND=postgres` in a second terminal, the
deployed URL in the browser, the dashboard tab open, Label Studio running.
