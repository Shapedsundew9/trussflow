"""Basic tests for the Trussflow CLI."""

from __future__ import annotations

import json
from pathlib import Path

from trussflow.cli import RN_CHARS, main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="ascii")


def _create_valid_tree(base: Path) -> None:
    requirements = base / "requirements"
    _write(
        requirements / "root.json",
        json.dumps(
            {
                "ruid": "A0c",
                "timestamp": "2026-05-30T12:00:00Z",
                "text": "The product shall define a valid root requirement.",
                "rationale": "This is the top-level requirement.",
                "scope": "in",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write(
        requirements / "A" / "AB1c.json",
        json.dumps(
            {
                "ruid": "AB1c",
                "timestamp": "2026-05-30T12:10:00Z",
                "text": "The system shall define one valid child requirement.",
                "rationale": "This establishes hierarchy for validation.",
                "scope": "in",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _create_valid_change_artifacts(base: Path) -> None:
    _write(
        base / "errata" / "batch-001.json",
        json.dumps(
            [
                {
                    "errata_id": "ERR-A-20260530T120000Z",
                    "discovered_timestamp": "2026-05-30T12:00:00Z",
                    "analyst_id": "agent.requirement-analyst",
                    "error_type": "gap",
                    "description": "A measurable child requirement is missing.",
                    "affected_ruids": ["A0c"],
                    "violated_rule": "text.verifiability",
                    "root_cause": "Current text is not measurable.",
                    "solutions": [
                        {
                            "solution_id": "primary",
                            "action_type": "create_requirement",
                            "description": "Create measurable child requirement.",
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    _write(
        base / "amendments" / "batch-001.json",
        json.dumps(
            [
                {
                    "amendment_id": "AMD-A-20260530T121500Z",
                    "errata_id": "ERR-A-20260530T120000Z",
                    "selected_solution_id": "primary",
                    "approved_by": "ccb.user",
                    "approval_timestamp": "2026-05-30T12:15:00Z",
                    "changes": [
                        {
                            "change_id": "CHG-000001",
                            "action": "create",
                            "parent_ruid": "A0c",
                            "new_ruid": "AC1p",
                            "new_timestamp": "2026-05-30T12:16:00Z",
                            "new_state": {
                                "text": "The system shall define one measurable child requirement.",
                                "rationale": "Supports verifiability.",
                                "scope": "in",
                                "refs": {
                                    "depends_on": [],
                                    "related_to": [],
                                    "supersedes": [],
                                },
                            },
                        }
                    ],
                }
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _create_sibling_exhausted_tree(base: Path) -> None:
    requirements = base / "requirements"
    _write(
        requirements / "root.json",
        json.dumps(
            {
                "ruid": "A0c",
                "timestamp": "2026-05-30T12:00:00Z",
                "text": "The product shall define a valid root requirement.",
                "rationale": "This is the top-level requirement.",
                "scope": "in",
                "refs": {
                    "depends_on": [],
                    "related_to": [],
                    "supersedes": [],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    for token in RN_CHARS:
        ruid = f"A{token}1c"
        _write(
            requirements / "A" / f"{ruid}.json",
            json.dumps(
                {
                    "ruid": ruid,
                    "timestamp": "2026-05-30T12:10:00Z",
                    "text": "The system shall define one valid child requirement.",
                    "rationale": "This establishes hierarchy for validation.",
                    "scope": "in",
                    "refs": {
                        "depends_on": [],
                        "related_to": [],
                        "supersedes": [],
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )


def test_cli_version(capsys):
    code = main(["--version"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out


def test_cli_validate_default_path_success(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["validate"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Validation PASSED" in out


def test_cli_validate_json_failure_for_missing_path(capsys):
    code = main(["validate", "does-not-exist", "--json"])
    out = capsys.readouterr().out

    payload = json.loads(out)
    assert code == 1
    assert payload["valid"] is False
    assert payload["error_count"] >= 1
    first_error = payload["errors"][0]
    assert "error_code" in first_error
    assert first_error["error_code"] == first_error["rule"]


def test_cli_validate_changes_success(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    _create_valid_change_artifacts(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["validate-changes"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Validation PASSED" in out


def test_cli_validate_changes_json_failure_for_missing_errata(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    _create_valid_change_artifacts(tmp_path)
    monkeypatch.chdir(tmp_path)

    (tmp_path / "errata" / "batch-001.json").unlink()

    code = main(["validate-changes", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 1
    assert payload["valid"] is False
    assert payload["error_count"] >= 1
    assert any(err["error_code"] == "artifact.empty" for err in payload["errors"])


def test_cli_requirement_get_json_success(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["requirement", "get", "AB", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["selector"] == "AB"
    assert payload["result"]["rn"] == "AB"
    assert payload["result"]["ruid"] == "AB1c"
    assert payload["result"]["requirement"]["ruid"] == "AB1c"


def test_cli_requirement_get_accepts_ruid_suffix_mismatch(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["requirement", "get", "AB1p", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["rn"] == "AB"
    assert payload["result"]["ruid"] == "AB1c"


def test_cli_requirement_list_parent_filter(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["requirement", "list", "--parent", "A", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["count"] == 1
    assert payload["result"]["items"][0]["ruid"] == "AB1c"


def test_cli_requirement_list_root_only_filter(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(["requirement", "list", "--root-only", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["count"] == 1
    assert payload["result"]["items"][0]["ruid"] == "A0c"


def test_cli_requirement_list_include_projection(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "list",
            "--parent",
            "A",
            "--include",
            "ruid,text",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["count"] == 1
    assert sorted(payload["result"]["items"][0].keys()) == ["ruid", "text"]
    assert payload["result"]["items"][0]["ruid"] == "AB1c"


def test_cli_requirement_list_include_invalid_field(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "list",
            "--include",
            "ruid,unknown_field",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["error_code"] == "list.include.invalid"


def test_cli_requirement_create_child_dry_run(tmp_path: Path, monkeypatch, capsys):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-child",
            "A",
            "--rl",
            "1",
            "--rs",
            "p",
            "--text",
            "The system shall define another child requirement.",
            "--rationale",
            "Covers additional scope.",
            "--scope",
            "in",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["ruid"] == "A01p"
    assert not (tmp_path / "requirements" / "A" / "A01p.json").exists()


def test_cli_requirement_create_root_dry_run(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-root",
            "--rs",
            "p",
            "--text",
            "The product shall define the initial root requirement.",
            "--rationale",
            "Bootstrap the requirements tree.",
            "--scope",
            "in",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is True
    assert payload["result"]["ruid"] == "00p"
    assert not (tmp_path / "requirements" / "root.json").exists()


def test_cli_requirement_create_root_apply_writes_root_file(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-root",
            "--rs",
            "p",
            "--text",
            "The product shall define the initial root requirement.",
            "--rationale",
            "Bootstrap the requirements tree.",
            "--scope",
            "in",
            "--apply",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is False

    root_path = tmp_path / "requirements" / "root.json"
    assert root_path.exists()

    doc = json.loads(root_path.read_text(encoding="ascii"))
    assert doc["ruid"] == "00p"
    assert doc["scope"] == "in"


def test_cli_requirement_create_root_fails_if_tree_exists(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-root",
            "--rs",
            "p",
            "--text",
            "The product shall define another root requirement.",
            "--rationale",
            "Should fail because root already exists.",
            "--scope",
            "in",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["error_code"] == "requirement.root.exists"


def test_cli_requirement_create_child_apply_writes_file(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-child",
            "A",
            "--rl",
            "1",
            "--rs",
            "p",
            "--text",
            "The system shall define another child requirement.",
            "--rationale",
            "Covers additional scope.",
            "--scope",
            "in",
            "--apply",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is False

    written_path = tmp_path / "requirements" / "A" / "A01p.json"
    assert written_path.exists()

    doc = json.loads(written_path.read_text(encoding="ascii"))
    assert doc["ruid"] == "A01p"
    assert doc["scope"] == "in"


def test_cli_requirement_create_child_accepts_all_ref_types(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-child",
            "A",
            "--rl",
            "1",
            "--rs",
            "p",
            "--text",
            "The system shall define another child requirement.",
            "--rationale",
            "Covers additional scope.",
            "--scope",
            "in",
            "--depends-on",
            "A",
            "--related-to",
            "AB1p",
            "--ref",
            "supersedes:AB",
            "--apply",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True

    written_path = tmp_path / "requirements" / "A" / "A01p.json"
    doc = json.loads(written_path.read_text(encoding="ascii"))
    assert doc["refs"]["depends_on"] == ["A"]
    assert doc["refs"]["related_to"] == ["AB"]
    assert doc["refs"]["supersedes"] == ["AB"]


def test_cli_requirement_create_sibling_accepts_generic_ref_arg(
    tmp_path: Path, monkeypatch, capsys
):
    _create_valid_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-sibling",
            "AB",
            "--rl",
            "1",
            "--rs",
            "p",
            "--text",
            "The system shall define a sibling requirement.",
            "--rationale",
            "Extends sibling coverage.",
            "--scope",
            "in",
            "--ref",
            "depends_on=A0c",
            "--ref",
            "related_to:AB",
            "--ref",
            "supersedes=AB1c",
            "--apply",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["ok"] is True

    written_path = tmp_path / "requirements" / "A" / "A01p.json"
    doc = json.loads(written_path.read_text(encoding="ascii"))
    assert doc["refs"]["depends_on"] == ["A"]
    assert doc["refs"]["related_to"] == ["AB"]
    assert doc["refs"]["supersedes"] == ["AB"]


def test_cli_requirement_create_sibling_exhausted_has_guidance(
    tmp_path: Path, monkeypatch, capsys
):
    _create_sibling_exhausted_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "requirement",
            "create-sibling",
            "AA",
            "--rl",
            "1",
            "--rs",
            "p",
            "--text",
            "The system shall define one more sibling requirement.",
            "--rationale",
            "Used to test sibling exhaustion handling.",
            "--scope",
            "in",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["errors"][0]["error_code"] == "rn.exhausted"
    assert "Direction: add hierarchy depth" in payload["errors"][0]["message"]
