# Trussflow

Trussflow is a requirements definition tool that helps you build out a software project so that it can be rebuilt from scratch without human intervention.

## Project Setup

Install in editable mode:

```bash
pip install -e .
```

Run tests:

```bash
pytest
```

Run the CLI:

```bash
trussflow --version
python -m trussflow --version
```

Validate requirements (schema + hierarchy + cross-reference checks):

```bash
trussflow validate
python -m trussflow validate
```

Validate a custom requirements directory:

```bash
trussflow validate path/to/requirements
```

Emit machine-readable output:

```bash
trussflow validate --json
```

Validate Errata and Amendment artifacts against requirements baseline:

```bash
trussflow validate-changes --requirements requirements --errata errata --amendments amendments
```

Requirement query commands:

Selectors use RUID only (for example `AB`).

```bash
trussflow requirement get AB --json
trussflow requirement list --root-only --json
trussflow requirement list --parent A --json
trussflow requirement list --parent A --include ruid,text --json
trussflow requirement inspect AB --include parent,siblings,children,refs --json
```

Mechanical requirement creation commands (dry-run by default):

RUID allocation is automatic. For each parent RUID, the next value is the first unused
one-character extension in this order: `0-9`, then `A-Z`. For the root in an empty
tree, the first RUID is `0`. Root `rl` is fixed to `0` and root `rs` defaults to `p`.
Reference selectors for `--depends-on`, `--related-to`, `--supersedes`, and `--ref`
must be RUID values (for example `AB`).

```bash
trussflow requirement create-root \
 --text "The product shall ..." \
 --rationale "..." \
 --scope in \
 --apply --json

trussflow requirement create-child A \
 --text "The system shall ..." \
 --rationale "..." \
 --scope in \
 --json

trussflow requirement create-sibling AB \
 --text "The system shall ..." \
 --rationale "..." \
 --scope in \
 --apply --json
```

Prompt template rendering:

Use `prompt render` to replace `{{PLACEHOLDER}}` tokens in a prompt file using repeated
`--var KEY=VALUE` arguments. By default, rendered files are written under `.trussflow/tmp`.

```bash
trussflow prompt render docs/prompts/requirement-seed-writer.md \
 --var SOURCE_DOCUMENT_PATH=docs/design/req-spec.md \
 --var RL=1

trussflow prompt render docs/prompts/requirement-seed-writer.md \
 --var SOURCE_DOCUMENT_PATH=docs/design/req-spec.md \
 --var RL=1 \
 --output .trussflow/tmp/seed-rendered.md \
 --json
```
