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

Selectors can be RN (`AB`) or full RUID (`AB1c`).

```bash
trussflow requirement get AB --json
trussflow requirement list --root-only --json
trussflow requirement list --parent A --json
trussflow requirement list --parent A --include ruid,text --json
trussflow requirement inspect AB --include parent,siblings,children,refs --json
```

Mechanical requirement creation commands (dry-run by default):

RN allocation is automatic. For each parent RN, the next value is the first unused
one-character extension in this order: `0-9`, then `A-Z`. For the root in an empty
tree, the first RN is `0`. Root RL is fixed to `0`.
Reference selectors for `--depends-on`, `--related-to`, `--supersedes`, and `--ref`
can be provided as RN (for example `AB`) or full RUID (for example `AB1p`), but
Trussflow always stores refs as RN only.

```bash
trussflow requirement create-root \
 --rs p \
 --text "The product shall ..." \
 --rationale "..." \
 --scope in \
 --apply --json

trussflow requirement create-child A \
 --rl 1 --rs p \
 --text "The system shall ..." \
 --rationale "..." \
 --scope in \
 --json

trussflow requirement create-sibling AB \
 --rl 1 --rs p \
 --text "The system shall ..." \
 --rationale "..." \
 --scope in \
 --apply --json
```
