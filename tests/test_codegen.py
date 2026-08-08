"""M2 codegen contract tests.

These guard the properties that make generated Java *deliverable* rather than
merely syntactically plausible:

  * every CLI template traces to the CLI doc (no invented commands),
  * unvalidated expectations can never render as a passing assertion,
  * step IDs stay stable across regenerations (reviewers cite them),
  * emitted source is plain ASCII, like the rest of Exaware's tree.

Compilation against the real framework is the other half of the gate and lives
outside pytest — it needs the mirrored `cmp-infra-project` / `cmp-tests-project`
sources and their jars. See `.claude/skills/exaware-framework`.
"""
from __future__ import annotations

import pytest

from ate.codegen.commands import (
    EVPN_COMMANDS,
    UngroundedCommandError,
    validate_grounding,
)
from ate.codegen.evpn_scripts import evpn_scripts
from ate.codegen.java_emitter import emit_all
from ate.codegen.lab import SINGLE_DUT_3AC
from ate.codegen.script_ir import StepKind
from ate.planner.cli_extractor import CliCommand


@pytest.fixture(scope="module")
def scripts():
    return evpn_scripts(SINGLE_DUT_3AC)


@pytest.fixture(scope="module")
def files(scripts):
    return emit_all(scripts, SINGLE_DUT_3AC)


def test_three_m2_flows_are_generated(scripts):
    """Exaware scoped M2 to exactly these three flows (Eyal, 2026-08)."""
    assert [s.flow_id for s in scripts] == ["FLOW-010", "FLOW-030", "FLOW-031"]


def test_flow_010_is_the_declared_prerequisite(scripts):
    by_id = {s.flow_id: s for s in scripts}
    assert by_id["FLOW-010"].depends_on == []
    assert "FLOW-010" in by_id["FLOW-030"].depends_on
    assert "FLOW-010" in by_id["FLOW-031"].depends_on


def test_step_ids_are_stable_and_unique(scripts):
    """Step IDs are cited in review and keyed on by the dirty queue, so they
    must not drift between runs (same contract as flow IDs)."""
    ids = [st.id for sc in scripts for st in sc.steps]
    assert len(ids) == len(set(ids))
    for sc in scripts:
        for st in sc.steps:
            assert st.id.startswith(sc.flow_id + ".S"), st.id


def test_every_command_template_is_grounded_in_the_cli_doc():
    catalog = [CliCommand(name=c.source, kind="config", syntax="")
               for c in EVPN_COMMANDS if c.source]
    assert validate_grounding(catalog) is not None


def test_ungrounded_command_is_fatal():
    """An invented command must stop generation, not warn. This is the
    cli_crosscheck posture carried into codegen."""
    with pytest.raises(UngroundedCommandError):
        validate_grounding([CliCommand(name="evpn", kind="config", syntax="")])


def test_unvalidated_expectations_never_assert_a_pass(files, scripts):
    """A step awaiting real device output must emit a warning, and its
    expectation constant must be empty — an empty array makes EvpnUtils warn
    instead of pass."""
    params = next(f for f in files if f.class_name == "EvpnParams")
    todo_steps = [st for sc in scripts for st in sc.open_todos]
    assert todo_steps, "fixture should still have open TODOs"

    tests = {f.class_name: f.content for f in files
             if f.class_name.startswith("TC")}
    joined = "\n".join(tests.values())
    for st in todo_steps:
        assert f"CompassReporter.warning(\"{st.id}" in joined, st.id
        if st.expect_key:
            assert f"{st.expect_key} = new String[] {{}}" in params.content


def test_emitted_java_is_ascii(files):
    for f in files:
        f.content.encode("ascii")  # raises if any prose leaked through


def test_traffic_steps_reference_declared_items(scripts):
    declared = {t.name for t in SINGLE_DUT_3AC.traffic_items}
    for sc in scripts:
        for st in sc.steps:
            if st.kind is StepKind.TRAFFIC_STATE:
                assert st.traffic_items, st.id
                assert set(st.traffic_items) <= declared, st.id
                assert st.enabled is not None, st.id


def test_local_mac_move_asserts_no_readvertisement(scripts):
    """Eyal's 2026-07-06 annotation on FLOW-030: a MAC moving between two
    LOCAL ACs on the same PE must NOT trigger a new Type-2 advertisement.
    The generated suite has to keep asserting it."""
    flow030 = next(s for s in scripts if s.flow_id == "FLOW-030")
    no_event = [st for st in flow030.steps
                if st.kind is StepKind.VERIFY_NO_EVENT]
    assert len(no_event) == 2, "expected a snapshot step and a compare step"
    assert any("no new type-2" in st.text.lower() for st in no_event)


def test_generated_files_are_the_four_artifact_kinds(files):
    names = {f.class_name for f in files}
    assert {"EvpnCommands", "EvpnParams", "EvpnUtils"} <= names
    assert sum(1 for n in names if n.startswith("TC")) == 3
    for f in files:
        assert f.path.startswith("cmp/tests/evpn/")


def test_test_classes_extend_the_framework_base_class(files):
    for f in files:
        if f.class_name.startswith("TC"):
            assert "extends CmpTestCase" in f.content
            assert "import cmp.infra.CmpTestCase;" in f.content
            assert "@Test" in f.content


def test_requirement_provenance_reaches_the_java(files, scripts):
    """Traceability must survive into the source: a reviewer reading the
    generated file can get back to the SFS/RFC anchor."""
    joined = "\n".join(f.content for f in files if f.class_name.startswith("TC"))
    for sc in scripts:
        for rid in sc.covered_req_ids:
            assert rid.replace("§", "section ") in joined or rid in joined, rid
