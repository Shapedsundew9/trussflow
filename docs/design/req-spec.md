# Requirement Specification

The lineage framework starts from requirements that are independent of technology and architecture.

## Goals

Requirements shall:

* Define in-scope and out-of-scope behavior explicitly.
* Use a nested hierarchy.
* Use immutable, globally unique identifiers.
* Preserve parent-child traceability through identifier structure.
* Encode decomposition stage in the RUID independent of hierarchy depth.
* Use controlled terminology.
* Declare explicit cross-references.
* Use concise ASCII text optimized for AI processing.

## RUID Definition

RUID (Requirement Unique Identifier) format:

* Regex: `[0-9A-Z]+[0-3][cpt]`
* Structure: RN + RL + RS

### RN (Requirement Number)

* Regex: [0-9A-Z]+
* RN is globally and eternally unique across the project.
* No two requirements shall share the same RN, regardless of RS.
* RN is hierarchical.
* Each child RN shall equal parent RN plus exactly one additional character.

### RL (Requirement Level)

RL encodes decomposition stage and is not the same as hierarchy depth.

* 0: Level 0 - Product Vision & User Goals
* 1: Level 1 - Software System Requirements
* 2: Level 2 - Architectural & Subsystem Specs
* 3: Level 3 - Component Design Specifications

Rules:

* RL is mandatory for every requirement as part of RUID.
* Child RL shall be greater than or equal to parent RL.
* A child may keep the same RL as its parent.
* RL transitions are not required at each hierarchy level.
* A requirement with RL 3 shall have at least one ancestor with RL 0, 1, or 2.

### RS (Requirement State)

* c: committed
* p: proposed
* t: to-be-defined

## Immutability Rules

* A RUID is immutable after publication.
* Requirement edits that change meaning, RS, scope, or references shall create a new requirement with a new RN.
* The new requirement shall reference the replaced requirement via refs.supersedes.

## State and Hierarchy Constraints

* If parent RS is p, all descendants shall have RS p.
* If RS is t, the requirement shall be a leaf (no children).
* If parent RS is c, children may be c, p, or t.

## Storage Model

Requirements are stored under requirements/ using RN-based folders.

* Root file: requirements/root.json
* Root folder: `requirements/<root-rn>/`
* Each requirement is stored in exactly one JSON file.
* A descendant requirement is stored at `requirements/<parent-rn>/<child-ruid>.json`
* A requirement gets its own folder only if it has children.
* Empty folders are forbidden.

## JSON Format

All files shall be ASCII JSON.

### Requirement File Schema

Each requirement file shall contain one JSON object with this schema:

* ruid: string, required, regex `[0-9A-Z]+[0-3][cpt]`
* timestamp: string, required, creation timestamp in UTC, regex `[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z`
* text: string, required, concise requirement statement using shall
* rationale: string, required, concise justification for the requirement
* scope: enum, required, one of [in, out]
* refs: object, required
* refs.depends_on: array of RUID strings, optional, default []
* refs.related_to: array of RUID strings, optional, default []
* refs.supersedes: array of RUID strings, optional, default []

Rules:

* Every referenced RUID shall exist.
* refs.supersedes shall only point to older requirements.
* timestamp shall be an ISO 8601 UTC instant using the form YYYY-MM-DDTHH:MM:SSZ.
* Validator JSON output shall include a stable error_code field per violation for machine processing.

## Example

Example file requirements/A/AB1c.json:

```json
{
  "ruid": "AB1c",
  "timestamp": "2026-05-30T12:00:00Z",
  "text": "The system shall validate incoming requirement files before merge.",
  "rationale": "Early validation prevents invalid requirements from entering the baseline.",
  "scope": "in",
  "refs": {
    "depends_on": ["AA1c"],
    "related_to": ["XZ2p"],
    "supersedes": []
  }
}
```

## Controlled Terminology

Only the terms in this glossary shall be used with normative meaning.

* Requirement: One atomic normative statement with one immutable RUID.
* Parent: A requirement whose RN is a strict prefix of child RN.
* Child: A requirement whose RN extends parent RN by exactly one character.
* Descendant: Any recursive child of a parent.
* Leaf: A requirement with no children.
* Requirement Level (RL): Decomposition stage token in RUID in the range 0-3; independent of hierarchy depth.
* Scope: Inclusion status of a requirement, either in or out.
* Cross-reference: A typed link in refs to another requirement.
* Supersedes: A replacement relation from a newer requirement to an older one.
