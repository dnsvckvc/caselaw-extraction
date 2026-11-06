-- Extracted records of the case-law extraction pipeline (week 3). One database holds several
-- extraction runs; every record row carries its run_id. Decision texts are run-independent
-- (`decision_text`, loaded once from the corpus for the text endpoint of the API).

CREATE TABLE IF NOT EXISTS extraction_run (
    run_id            text PRIMARY KEY,
    extractor         text NOT NULL,
    extractor_version text,
    started_at        timestamptz,
    n_decisions       integer,
    n_spans           integer,
    wall_seconds      double precision,
    workers           integer,
    scheduler         text,
    loaded_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision (
    run_id          text NOT NULL REFERENCES extraction_run(run_id) ON DELETE CASCADE,
    decision_id     text NOT NULL,
    docket_number   text,
    decision_date   date,
    year            integer,
    chamber         text,
    legal_area      text,
    outcome_dataset text,
    outcome         text,
    text_length     integer,
    source_url      text,
    n_spans         integer,
    n_dropped       integer,
    PRIMARY KEY (run_id, decision_id)
);

CREATE TABLE IF NOT EXISTS span (
    run_id      text NOT NULL REFERENCES extraction_run(run_id) ON DELETE CASCADE,
    span_id     text NOT NULL,
    decision_id text NOT NULL,
    start_char  integer NOT NULL,
    end_char    integer NOT NULL,
    label       text NOT NULL,
    text        text NOT NULL,
    PRIMARY KEY (run_id, span_id)
);

CREATE TABLE IF NOT EXISTS citation (
    run_id             text NOT NULL REFERENCES extraction_run(run_id) ON DELETE CASCADE,
    citation_id        bigserial PRIMARY KEY,
    span_id            text NOT NULL,
    decision_id        text NOT NULL,
    kind               text NOT NULL CHECK (kind IN ('statute', 'bge', 'docket')),
    key                text NOT NULL,
    code               text,
    sr                 text,
    article            text,
    target_decision_id text
);

-- One row per node and graph variant: `all` (every citation) or `no_routine` (citations that
-- Jev 1.14 labelled routine_standard left out), for the API's routine selector.
CREATE TABLE IF NOT EXISTS centrality (
    run_id         text NOT NULL REFERENCES extraction_run(run_id) ON DELETE CASCADE,
    variant        text NOT NULL DEFAULT 'all',
    node           text NOT NULL,
    kind           text NOT NULL,
    key            text NOT NULL,
    decision_id    text,
    in_degree      integer NOT NULL,
    out_degree     integer NOT NULL,
    pagerank       double precision NOT NULL,
    rank_pagerank  integer NOT NULL,
    rank_in_degree integer NOT NULL,
    PRIMARY KEY (run_id, variant, node)
);

-- Databases created before the routine selector: add the variant to the centrality key.
ALTER TABLE centrality ADD COLUMN IF NOT EXISTS variant text NOT NULL DEFAULT 'all';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.key_column_usage
        WHERE table_name = 'centrality' AND constraint_name = 'centrality_pkey'
          AND column_name = 'variant'
    ) THEN
        ALTER TABLE centrality DROP CONSTRAINT centrality_pkey;
        ALTER TABLE centrality ADD PRIMARY KEY (run_id, variant, node);
    END IF;
END $$;

-- Citation treatment by Jev 1.14 (`caselaw treatment`), one row per bge/docket citation span.
-- Loaded later than the run; a citation without a row counts as not routine.
CREATE TABLE IF NOT EXISTS citation_treatment (
    run_id   text NOT NULL REFERENCES extraction_run(run_id) ON DELETE CASCADE,
    span_id  text NOT NULL,
    label    text NOT NULL,
    p        double precision,
    model    text NOT NULL,
    PRIMARY KEY (run_id, span_id)
);

CREATE TABLE IF NOT EXISTS decision_text (
    decision_id text PRIMARY KEY,
    text        text NOT NULL
);

CREATE TABLE IF NOT EXISTS statute (
    sr           text PRIMARY KEY,
    abbreviation text NOT NULL,
    title        text
);

CREATE INDEX IF NOT EXISTS citation_key_idx ON citation (run_id, kind, key);
CREATE INDEX IF NOT EXISTS citation_decision_idx ON citation (run_id, decision_id);
CREATE INDEX IF NOT EXISTS citation_target_idx ON citation (run_id, target_decision_id);
CREATE INDEX IF NOT EXISTS span_decision_idx ON span (run_id, decision_id);
CREATE INDEX IF NOT EXISTS decision_year_idx ON decision (run_id, year);
DROP INDEX IF EXISTS centrality_pagerank_idx;
CREATE INDEX IF NOT EXISTS centrality_variant_pagerank_idx
    ON centrality (run_id, variant, pagerank DESC);
CREATE INDEX IF NOT EXISTS citation_span_idx ON citation (run_id, span_id);
