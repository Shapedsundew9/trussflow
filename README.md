# Trussflow

Trussflow is a requirements definition tool that helps you build out a software project so that it can be rebuilt from scratch without human intervention.

## Prototype quickstart

The prototype ingests an unstructured vision document, uses an AI agent to
extract NASA-style requirements into a Memgraph knowledge graph, grades their
quality, and runs structural gap analysis. It runs fully offline using a
deterministic stub LLM, or against Google Gemini when configured.

```bash
# Install (editable)
pip install -e .

# Configure (dev container defaults: Memgraph compose service, offline stub LLM)
cp .env.example .env

# Run the pipeline
trussflow health                       # check Memgraph connectivity
trussflow ingest docs/design/vision.md # vision -> requirements graph
trussflow grade                        # score requirement quality
trussflow decompose                    # extract features, group requirements
trussflow workpackages                 # generate work packages (IMPLEMENTS)
trussflow derive REQ-104 --type System # derive lower-level child requirements
trussflow impact REQ-104               # show downstream impact of a change
trussflow supersede REQ-104 --text "The system shall ..."  # record a change trail
trussflow analyze                      # structural gap analysis
trussflow list                         # list stored requirements
trussflow features                     # list stored features
trussflow reset                        # delete all graph data (destructive)
```

### Configuration

Settings are environment-driven (see [.env.example](.env.example)):

- `MEMGRAPH_HOST` / `MEMGRAPH_PORT` — graph database connection.
- `TRUSSFLOW_LLM_PROVIDER` — `stub` (offline, default) or `gemini`.
- `GEMINI_API_KEY` / `TRUSSFLOW_GEMINI_MODEL` — required for the Gemini provider
  (`pip install -e .[gemini]`).

Visualize the graph in Memgraph Lab at <http://localhost:3000>. Raw agent
input/output is written to `artifacts/` for transparency.

### Architecture

- `config` — environment settings and structured logging.
- `models` — dataclasses mirroring the Memgraph node/edge schema.
- `store/graph` — idempotent Bolt-protocol graph access and gap queries.
- `llm` — pluggable provider protocol (`stub`, `gemini`) + factory.
- `prompts` — load `docs/prompts/*.md` with mechanical placeholder substitution.
- `agents` — `seed_writer` (extraction), `analyst` (grading), `feature_extractor`,
  `work_packager`, and `decomposer` (multi-level derivation), all schema-validated.
- `pipeline` — plain-Python orchestration with artifact persistence.
- `analysis` — gap-analysis reporting.
- `cli` — `trussflow` command entry point.

The graph follows `docs/design/memgraph-schema.md`:
`Vision <- Feature <- Requirement <- Requirement (Product/System/Design)`, with
`WorkPackage -[:IMPLEMENTS]-> Requirement`, `-[:DEPENDS_ON]->`, and
`-[:SUPERSEDES]->` edges for change trails and impact analysis.
