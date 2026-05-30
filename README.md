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
