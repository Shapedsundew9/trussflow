# Requirement Gap, Contradictions & Irrecoverable Errors

During the requirement review process, if a requirements agent identifies gaps, contradictions, or other irrecoverable errors, they must document these findings in a strictly formatted, machine-readable Errata file. Because the agent possesses the necessary context regarding the issue and potential resolutions, the Errata file must include the specific requirement file and requirements involved, a proposed solution, and up to three alternative solutions.

The objective is for a Python program to ingest this Errata and present the user with solution options for selection. This selection process then generates an Amendment file containing non-trivial updates to the requirement structure. Each amendment is subsequently fed into a requirement writer agent that incorporates the changes into the hierarchy. While some insertions may be mechanical and handled by script, others involving significant user feedback may result in a cascading hierarchy of requirements managed by the writer agent.

## Artifact Format

Errata and Amendment artifacts are ASCII JSON files with top-level arrays.

* Errata schema: `schemas/errata.schema.json`
* Amendment schema: `schemas/amendment.schema.json`
* Errata location: `errata/*.json`
* Amendment location: `amendments/*.json`

## Errata Contract

Each Errata entry includes:

* identity and metadata: `errata_id`, `discovered_timestamp`, `analyst_id`
* issue definition: `error_type`, `description`, `violated_rule`, optional `root_cause`
* affected requirements: `affected_ruids`
* proposed responses: `solutions` (1 to 3 entries)

Rules:

* `solutions` has a maximum of three options per errata entry.
* each solution contains `solution_id`, `action_type`, and `description`.
* all RUID values must match `[0-9A-Z]+[0-3][cpt]`.

## Amendment Contract

Each Amendment entry includes:

* identity and linkage: `amendment_id`, `errata_id`, `selected_solution_id`
* approval metadata: `approved_by`, `approval_timestamp`
* `changes`: one or more atomic actions

Supported actions:

* `create`
* `supersede`
* `state_transition`
* `scope_change`
* `ref_update`
* `move_hierarchy`

Per-action required operands are enforced in schema using conditional validation.

## Semantic Validation Rules

In addition to schema validation:

* each `affected_ruids` value in Errata must exist in the requirements baseline.
* each Amendment `errata_id` must resolve to an existing Errata entry.
* Amendment `selected_solution_id` must exist in the linked Errata `solutions`.
* changes that target published requirements (RS=`c`) may not modify in place for state/scope/ref/hierarchy operations; they must use `supersede`.

Validate all three artifacts together using:

* `trussflow validate-changes --requirements requirements --errata errata --amendments amendments`
