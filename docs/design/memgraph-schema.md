# 1. Node Labels & Property Schema

Each node in Memgraph will represent an entity in your development pipeline, tracking metadata to feed into the AI grading, verification, and gap analysis loops .

## `(:Vision)`

The root node representing the high-level unstructured goal of the project or founder .

* `id`: `STRING` (Unique identifier, e.g., `VIS-001`) .
* `text`: `STRING` (The raw snippet or transcript section it originated from) .
* `source`: `STRING` (e.g., `"Meeting Transcript - 2026-05-31"`) .

## `(:Feature)`

Intermediate capabilities or milestones broken down from the core vision .

* `id`: `STRING` (Unique identifier, e.g., `FEAT-001`) .
* `name`: `STRING` (Short human-readable summary) .
* `description`: `STRING` (Text describing the feature domain) .

## `(:Requirement)`

The atomic, formalized product, system architecture, or design specifications .

* `id`: `STRING` (Deterministic ID, e.g., `REQ-101`) .
* `text`: `STRING` (The NASA-compliant sentence: "The system shall...") .
* `rationale`: `STRING` (The "why" or intent behind the rule) .
* `type`: `STRING` (`"Product"`, `"System"`, `"Design"`, `"Implementation"`) .
* `status`: `STRING` (`"TBD"`, `"TBR"`, `"Defined"`, `"Approved"`, `"Superseded"`) .
* `user_concern`: `STRING` (`"High"` or `"Low"`. Dictates AI autonomy boundaries) .
* `quality_score`: `FLOAT` (Aggregated score assigned by the AI grading agent) .
* `is_atomic`: `BOOLEAN` (Flag for whether the requirement isolates a single thought) .
* `is_verifiable`: `BOOLEAN` (Flag indicating the requirement can be objectively verified) .

## `(:WorkPackage)`

The final execution-level tasks parsed for software developers or AI builders .

* `id`: `STRING` (e.g., `WP-001` or GitHub Issue reference) .
* `summary`: `STRING` (Actionable task instructions) .
* `scope`: `STRING` (`"Human"`, `"AI_Autonomous"`) .

## 2. Relationship Types (Edges)

Edges are explicitly typed and directed to ensure strict ancestry traversal and to completely bypass "join hell" when parsing the graph .

* `(:Feature)-[:CHILD_OF]->(:Vision)`: Maps a high-level feature directly to its business goal .
* `(:Requirement)-[:CHILD_OF]->(:Feature)`: Traces requirements up to their functional capabilities .
* `(:Requirement)-[:CHILD_OF]->(:Requirement)`: Models hierarchy between different requirement layers (Product $\rightarrow$ System $\rightarrow$ Design) .
* `(:Requirement)-[:DEPENDS_ON]->(:Requirement)`: Identifies linear prerequisites or functional dependencies .
* `(:Requirement)-[:SUPERSEDES]->(:Requirement)`: Keeps track of historical change trails when an architectural constraint forces an older requirement to change .
* `(:WorkPackage)-[:IMPLEMENTS]->(:Requirement)`: Closes the gap between target specification and actual task execution .

## 3. Structural Visual Representation

When queried inside Memgraph's visual layout, the schema tracks linearly outwards to map your project seamlessly:

```text
 (:Vision) 
     ▲
     │ [:CHILD_OF]
 (:Feature)
     ▲
     │ [:CHILD_OF]
 (:Requirement [Type: Product]) ◄──[:DEPENDS_ON]── (:Requirement)
     ▲
     │ [:CHILD_OF]
 (:Requirement [Type: System Architecture])
     ▲
     │ [:CHILD_OF]
 (:Requirement [Type: Design])
     ▲
     │ [:IMPLEMENTS]
 (:WorkPackage)

```

---

## 4. Leveraging Memgraph for Key Trussflow Goals

By implementing this specific schema, you can run rapid Cypher operations natively inside your Python backend to achieve Trussflow's target features :

## A. Automated Gap Analysis (Finding "Dangling" Requirements)

To detect features that do not trace back to any root vision (preventing "gold plating" or scope creep), your AI can execute a structural Cypher search :

```cypher
MATCH (f:Feature)
WHERE NOT (f)-[:CHILD_OF]->(:Vision)
RETURN f.id, f.name;

```

Similarly, to discover requirements that don't have actionable implementation tasks generated yet :

```cypher
MATCH (r:Requirement)
WHERE NOT (:WorkPackage)-[:IMPLEMENTS]->(r) AND r.status = "Approved"
RETURN r.id, r.text;

```

## B. AI Autonomy Guardrail Isolation

Trussflow mandates that AI agent loops can autonomously work on certain tasks only if they have minimal or zero impact on high-level user concerns . You can query Memgraph to fetch all low-concern dependencies dynamically :

```cypher
MATCH (r:Requirement {user_concern: "Low"})-[:CHILD_OF*1..3]->(parent:Requirement {user_concern: "High"})
RETURN r.id, r.text, parent.id AS binding_parent_id;

```

Your Python orchestration layer can pass this exact array of low-concern sub-nodes to an AI agent (the GitHub Copilot CLI) , letting it generate design parameters autonomously without letting it alter the human-governed "High" concern root rules .

## C. Impact Analysis (Managing Historical Trails)

If a system requirement needs to be flagged as `Superseded` during the architectural evaluation phase , you can track downstream effects using a variable-length path traversal :

```cypher
MATCH path = (root:Requirement {id: "REQ-101"})<-[:DEPENDS_ON|CHILD_OF*]-(dependent)
RETURN dependent.id, dependent.text, dependent.status;

```

This instantly gives your Python app a list of every affected design layer, allowing the AI to systematically prompt the user: *"REQ-101 has changed. Accept changes to rewrite the downstream requirements?"*
