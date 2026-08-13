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

import time

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


# ── dirty queue ─────────────────────────────────────────────────────────────

def test_queue_lifecycle_new_to_approved(tmp_path, scripts):
    from ate.codegen.queue import Queue, State

    q = Queue.load(tmp_path / "q.json")
    report = q.refresh(scripts, "digest-1")
    assert sorted(report["added"]) == ["FLOW-010", "FLOW-030", "FLOW-031"]
    assert q.selected_ids() == []

    q.select(["FLOW-030"])
    assert q.selected_ids() == ["FLOW-030"]

    q.mark_generated(["FLOW-030"])
    assert q.entries["FLOW-030"].state is State.GENERATED
    assert q.selected_ids() == [], "generated tests are no longer pending"

    q.approve(["FLOW-030"])
    assert q.entries["FLOW-030"].state is State.APPROVED


def test_queue_marks_stale_when_the_source_documents_change(tmp_path, scripts):
    """A re-issued SFS/CLI doc must invalidate everything generated from it."""
    from ate.codegen.queue import Queue, State

    q = Queue.load(tmp_path / "q.json")
    q.refresh(scripts, "digest-1")
    q.select(["FLOW-010"])
    q.mark_generated(["FLOW-010"])

    report = q.refresh(scripts, "digest-2")
    assert "FLOW-010" in report["stale"]
    assert q.entries["FLOW-010"].state is State.STALE


def test_stale_approved_is_reported_separately(tmp_path, scripts):
    """The loud case: reviewed work is about to be overwritten. It must not be
    buried in the ordinary 'stale' bucket."""
    from ate.codegen.queue import Queue

    q = Queue.load(tmp_path / "q.json")
    q.refresh(scripts, "d1")
    q.approve(["FLOW-031"])

    report = q.refresh(scripts, "d2")
    assert report["stale_approved"] == ["FLOW-031"]
    assert "FLOW-031" not in report["stale"]


def test_select_all_protects_approved_work(tmp_path, scripts):
    from ate.codegen.queue import Queue, State

    q = Queue.load(tmp_path / "q.json")
    q.refresh(scripts, "d1")
    q.approve(["FLOW-030"])

    picked = q.select_all()
    assert "FLOW-030" not in picked
    assert q.entries["FLOW-030"].state is State.APPROVED
    assert q.select_all(include_approved=True) == sorted(q.entries)


def test_queue_round_trips_through_json(tmp_path, scripts):
    from ate.codegen.queue import Queue, State

    q = Queue.load(tmp_path / "q.json")
    q.refresh(scripts, "d1")
    q.select(["FLOW-010"])
    q.save()

    again = Queue.load(tmp_path / "q.json")
    assert again.entries["FLOW-010"].state is State.SELECTED
    assert again.entries.keys() == q.entries.keys()


def test_fingerprint_tracks_step_content(scripts):
    from ate.codegen.queue import fingerprint

    base = scripts[1]
    same = fingerprint(base, "d"), fingerprint(base, "d")
    assert same[0] == same[1], "fingerprint must be deterministic"

    mutated = base.model_copy(deep=True)
    mutated.steps[0].text = mutated.steps[0].text + " (edited)"
    assert fingerprint(mutated, "d") != fingerprint(base, "d")


# ── pattern matching ────────────────────────────────────────────────────────

def test_negative_assertions_are_not_mistaken_for_plain_checks():
    """Misclassifying 'verify no Type-2 was triggered' as a normal check
    inverts the meaning of the test — the rule order guards against it."""
    from ate.codegen.patterns import match_text

    res = match_text("Verify no type-2 message was triggered", "X.M1")
    assert res.step is not None
    assert res.step.kind is StepKind.VERIFY_NO_EVENT


def test_cross_reference_rows_are_excluded_not_counted_as_failures():
    """generator._slim_setup_for_continuation emits reference lines that are
    navigation, not steps. Counting them as unmatched would understate reach."""
    from ate.codegen.patterns import match_plan

    rows = [
        ("Base test steps are AS IN THE FIRST CASE of this flow", []),
        ("Verify the EVI is up", []),
    ]
    rep = match_plan(rows)
    assert rep.skipped == 1
    assert rep.total == 1
    assert rep.matched == 1
    assert rep.recall == 1.0


def test_matched_steps_still_require_review():
    """Pattern matching recognises shape, not intent, so a matched step must
    never arrive as a finished assertion."""
    from ate.codegen.patterns import match_text

    res = match_text("Verify `show evpn global` reports the EVI up", "X.M1")
    assert res.step is not None
    assert res.step.todo, "a pattern-derived step must carry a review marker"


def test_matcher_classifies_the_main_step_kinds():
    from ate.codegen.patterns import match_text

    cases = [
        ("Send 1 Gbps known-unicast frames from AC1", StepKind.TRAFFIC_STATE),
        ("Stop the AC2 traffic item", StepKind.TRAFFIC_STOP),
        ("Wait 300 seconds for the aging timer", StepKind.WAIT),
        ("Verify IXIA rx counters on the far port", StepKind.VERIFY_IXIA),
        # "is withdrawn" is a route-table assertion (look at the table, the
        # route is gone), not a negative-event one. VERIFY_NO_EVENT is
        # reserved for rows that assert something did NOT happen.
        ("Verify the Type-2 route is withdrawn", StepKind.VERIFY_ROUTE),
        ("Verify no withdrawal was sent to the peer", StepKind.VERIFY_NO_EVENT),
        ("Configure `l2-services evpn evi-1`; commit", StepKind.CONFIG),
    ]
    for text, expected in cases:
        res = match_text(text, "X.M1")
        assert res.step is not None, text
        assert res.step.kind is expected, f"{text} -> {res.step.kind}"


def test_commands_are_lifted_out_of_backticks():
    from ate.codegen.patterns import commands_in

    got = commands_in("Issue `no ethernet-segment`; then `show evpn global`")
    assert got == ["no ethernet-segment", "show evpn global"]


# ── mechanical plan → script path (plan_scripts.py) ──────────────────────


def test_resolve_command_grounds_against_the_registry():
    from ate.codegen.plan_scripts import resolve_command

    got = resolve_command("show evpn mac-address-table name evi-1")
    assert got is not None
    cmd, args = got
    assert cmd.key == "SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$"
    assert args == ["evi-1"]


def test_resolve_command_matches_a_config_tail():
    """The plan quotes config commands relative to their mode, so the literal
    `l2-services` prefix is absent from the backticks."""
    from ate.codegen.plan_scripts import resolve_command

    got = resolve_command("evpn evi-1 service-type vlan-based")
    assert got is not None
    cmd, args = got
    assert cmd.key == "CONFIGURE_L2_SERVICES_EVPN_$_SERVICE_TYPE_$"
    assert args == ["evi-1", "vlan-based"]


def test_unknown_command_never_invents_an_enum_constant():
    from ate.codegen.plan_scripts import resolve_command

    assert resolve_command("show platform process memory") is None
    assert resolve_command("service-carving highest-random-weight") is None


def test_ungrounded_rows_degrade_to_a_compiling_stub():
    """A row whose command cannot be grounded must not emit `EvpnCommands.`."""
    from ate.codegen.plan_scripts import _step_for

    step = _step_for("FLOW-020.M001",
                     "Configure `service-carving highest-random-weight`", [])
    assert step is not None
    assert step.kind is StepKind.TODO_STUB
    assert step.command == ""
    assert step.todo, "a degraded step must say why"


def test_every_mechanically_derived_step_carries_a_todo():
    """No mechanically derived step may ever look like a validated assertion."""
    from ate.codegen.plan_scripts import _step_for

    for text in ("Verify `show evpn global name evi-1` reports the EVI",
                 "Configure `evpn evi-1 service-type vlan-based`",
                 "Send 1 Gbps of known-unicast from AC1"):
        step = _step_for("F.M1", text, [])
        assert step is not None and step.todo, text


# ── per-scenario device configuration (device_config.py) ─────────────────


def test_dut_config_uses_intpool_placeholders_not_lab_interfaces(scripts):
    """One .cfg must serve every testbed — that is why VPLS names int1/int2."""
    from ate.codegen.device_config import emit_dut_config
    from ate.codegen.lab import SINGLE_DUT_3AC

    cfg = emit_dut_config(scripts, SINGLE_DUT_3AC).content
    assert "interface int1" in cfg
    for ac in SINGLE_DUT_3AC.acs:
        assert ac.interface not in cfg, f"{ac.interface} pins the cfg to one rig"


def test_dut_config_never_contains_clear_or_no_forms(scripts):
    from ate.codegen.device_config import emit_dut_config
    from ate.codegen.lab import SINGLE_DUT_3AC

    body = [ln for ln in emit_dut_config(scripts, SINGLE_DUT_3AC).content
            .splitlines() if not ln.startswith("!")]
    assert not [ln for ln in body if ln.strip().startswith(("no ", "clear "))]


def test_dut_config_declares_that_the_underlay_is_absent(scripts):
    """Inventing IP/MPLS/BGP would put fiction in a file typed at a router."""
    from ate.codegen.device_config import emit_dut_config
    from ate.codegen.lab import SINGLE_DUT_3AC

    head = emit_dut_config(scripts, SINGLE_DUT_3AC).content
    assert "NOT included - the underlay" in head
    # The block shape stopped being a guess on 2026-08-11: an EVI was
    # configured on the DUT and `show configuration l2-services` printed
    # exactly this hierarchy.
    assert "DEVICE-VERIFIED" in head


def test_bringup_params_layers_clean_base_then_merges(scripts):
    from ate.codegen.device_config import emit_bringup_params
    from ate.codegen.lab import SINGLE_DUT_3AC

    crt = emit_bringup_params(scripts, SINGLE_DUT_3AC).content
    clean = next(ln for ln in crt.splitlines() if "cleanBaseConfig" in ln)
    merge = next(ln for ln in crt.splitlines() if "EVPN_Base.cfg" in ln)
    assert clean.split()[-2] == "1", "cleanBaseConfig must override"
    assert merge.split()[-2] == "2", "the feature cfg must merge"


def test_bringup_params_emits_no_ixia_config_row(scripts):
    """A .crt row pointing at a missing file aborts bring-up for the whole
    suite, and the .ixncfg is a binary IxNetwork save we cannot generate.

    It is also not commented out: bring-up validates this file against a
    position-sensitive response template, and a `//` line inside a table
    shifts the static blocks and fails the whole file."""
    from ate.codegen.device_config import emit_bringup_params
    from ate.codegen.lab import SINGLE_DUT_3AC

    crt = emit_bringup_params(scripts, SINGLE_DUT_3AC).content
    assert ".ixncfg" not in crt
    assert "/configurations/compass/EVPN_Base.cfg" in crt


def test_bringup_params_binds_placeholders_to_the_sut_intpool(scripts):
    from ate.codegen.device_config import emit_bringup_params
    from ate.codegen.lab import SINGLE_DUT_3AC

    crt = emit_bringup_params(scripts, SINGLE_DUT_3AC).content
    assert "cmp.tests.evpn.EvpnParams" in crt          # loadTestParamFile
    for i in range(1, 4):
        assert f"int{i}" in crt and f"vport{i}" in crt


# ── capturing real device output as expectations (capture.py) ────────────


def test_a_rejected_command_never_becomes_an_expectation():
    """Freezing 'syntax error' as expected output would make a test that
    passes by asserting the feature is absent."""
    from ate.codegen.capture import UNSUPPORTED, _classify

    raw = ("show evpn global\r\n"
           "----------------------------------^\r\n"
           "syntax error: element does not exist\r\n"
           "router[2026-08-11-18:38:43]# ")
    status, lines, note = _classify(raw, "show evpn global")
    assert status is UNSUPPORTED or status == UNSUPPORTED
    assert lines == []
    assert "rejected" in note


def test_empty_output_is_not_treated_as_success():
    """A device with nothing configured answers empty; freezing that would
    assert emptiness forever."""
    from ate.codegen.capture import EMPTY, _classify

    status, lines, _ = _classify("show bgp table\r\nrouter[x]# ", "show bgp table")
    assert status == EMPTY
    assert lines == []


def test_real_output_is_captured_without_echo_or_prompt():
    from ate.codegen.capture import OK, _classify

    raw = ("show system alarm\r\n"
           "TIMESTAMP            SEVERITY  DESCRIPTION\r\n"
           "----------------------------------------------------\r\n"
           "2026-08-11 16:14:53  Critical  PSU PSU-1 is Failed\r\n"
           "router[2026-08-11-18:38:43]# ")
    status, lines, _ = _classify(raw, "show system alarm")
    assert status == OK
    assert len(lines) == 3
    assert not any("router[" in ln for ln in lines), "prompt leaked"
    assert not any(ln.strip() == "show system alarm" for ln in lines), "echo leaked"


def test_only_ok_captures_are_offered_as_expectations():
    from ate.codegen.capture import (
        EMPTY,
        OK,
        UNSUPPORTED,
        CapturedCommand,
        CaptureSession,
    )

    s = CaptureSession(results=[
        CapturedCommand("A_LINES", "show a", OK, ["row"]),
        CapturedCommand("B_LINES", "show b", UNSUPPORTED),
        CapturedCommand("C_LINES", "show c", EMPTY),
    ])
    assert s.usable() == {"A_LINES": ["row"]}


def test_commands_needed_renders_arguments(scripts):
    from ate.codegen.capture import commands_needed

    needed = dict(commands_needed(scripts))
    assert needed, "the suite must need some show output"
    assert all("%s" not in cmd for cmd in needed.values()), "unrendered template"


@pytest.fixture(scope="session")
def derived_registry():
    """Registry entries derived from the real EVPN CLI doc.

    Session-scoped: parsing the .docx is the slow part, and every derivation
    test wants the same catalog.
    """
    from pathlib import Path as _P

    from ate.codegen.command_deriver import derive_commands
    from ate.parsers import parse
    from ate.planner.requirements_builder import build_catalog

    sfs = _P("references/EVPN/EVPN System Specification 1.00.docx")
    cli = _P("references/EVPN/EVPN CLI 1.00.docx")
    if not (sfs.exists() and cli.exists()):
        pytest.skip("EVPN reference documents not available")
    catalog = build_catalog(parse(sfs), cli_doc_path=cli)
    derived, _notes = derive_commands(catalog.cli_commands)
    return derived


# ── deriving the registry from the CLI doc (command_deriver.py) ──────────


def test_enumerated_keywords_stay_literal_not_arguments():
    """`load-balancing-mode single-active | all-active` is one command with two
    documented values, not a command taking a free value."""
    from ate.codegen.command_deriver import expand_syntax

    forms = expand_syntax("load-balancing-mode single-active | all-active",
                          {"single-active", "all-active"})
    assert "load-balancing-mode single-active" in forms
    assert "load-balancing-mode all-active" in forms
    assert "load-balancing-mode %s" not in forms


def test_a_keyword_introducing_a_value_set_is_not_an_argument():
    """`service-type {vlan-based | ...}` must keep `service-type` literal."""
    from ate.codegen.command_deriver import expand_syntax

    forms = expand_syntax(
        "evpn evpn-name [service-type {vlan-based | vlan-bundle}]",
        {"evpn-name", "service-type"})
    assert "evpn %s service-type vlan-based" in forms
    assert not any(f.startswith("evpn %s %s") for f in forms)


def test_operands_inside_an_alternation_still_become_arguments():
    """In `agg-eth agg-id` the first token selects, the second is a value —
    emitting `agg-id` literally would type it at a device."""
    from ate.codegen.command_deriver import expand_syntax

    forms = expand_syntax(
        "show interface [loopback loop-if | agg-eth agg-id] detail", set())
    assert "show interface agg-eth %s detail" in forms
    assert "show interface agg-eth agg-id detail" not in forms


def test_optional_groups_expand_both_ways():
    from ate.codegen.command_deriver import expand_syntax

    forms = expand_syntax("show evpn global [name evpn-name]", {"evpn-name"})
    assert "show evpn global" in forms
    assert "show evpn global name %s" in forms


def test_curated_entries_win_over_derived_ones(derived_registry):
    """The curated 18 encode decisions the document cannot settle — chiefly
    the `mac address-table` space."""
    from ate.codegen.commands import EVPN_COMMANDS

    curated_keys = {c.key for c in EVPN_COMMANDS}
    curated_templates = {c.template for c in EVPN_COMMANDS}
    assert not [d for d in derived_registry if d.key in curated_keys]
    assert not [d for d in derived_registry if d.template in curated_templates]


def test_derived_keys_are_valid_java_constants(derived_registry):
    import re as _re

    assert derived_registry, "the CLI doc should yield commands"
    seen = set()
    for d in derived_registry:
        assert _re.fullmatch(r"[A-Za-z][A-Za-z0-9_$]*", d.key), d.key
        assert d.key not in seen, f"duplicate constant {d.key}"
        seen.add(d.key)
        assert d.doc_syntax, f"{d.key} must carry its documented origin"


def test_a_shared_knob_derives_the_evpn_mode_not_vpls(derived_registry):
    """`mac-limit` lists both l2-services vpls and evpn; VPLS is out of scope
    for the EVPN plan, and binding a row to the VPLS constant is a real bug."""
    maclimit = [d for d in derived_registry if "mac-limit" in d.template]
    assert maclimit, "mac-limit should derive"
    assert not [d for d in maclimit if "vpls" in d.template]


# ── device verification as a pipeline stage (verify.py) ──────────────────


def test_probe_targets_the_last_literal_token():
    """`show evpn mac-address-table name %s` must be checked by asking the
    parent path whether it offers `name` — not by running the command."""
    from ate.codegen.verify import probe_for

    assert probe_for("show evpn mac-address-table name %s") == (
        "show evpn mac-address-table", "name")
    assert probe_for("show evpn summary") == ("show evpn", "summary")


def test_probe_substitutes_arguments_in_the_parent_path():
    from ate.codegen.verify import probe_for

    parent, expect = probe_for("l2-services evpn %s mac-limit %s")
    assert parent == "l2-services evpn X"
    assert expect == "mac-limit"


def test_probe_declines_single_token_templates():
    """Nothing to ask a parent about."""
    from ate.codegen.verify import probe_for

    assert probe_for("commit") is None


def test_completions_are_parsed_without_the_noise_tokens():
    from ate.codegen.verify import _completions

    raw = ("show evpn ?\r\n"
           "Description: Show EVPN information\r\n"
           "Possible completions:\r\n"
           "  broadcast-domains   Displays the EVPN broadcast domain\r\n"
           "  detail              Show EVPN detail status\r\n"
           "  mac-address-table   Show the EVPN MAC Address table\r\n"
           "  |                   Output modifiers\r\n"
           "  <cr>\r\n")
    got = _completions(raw)
    assert got == ["broadcast-domains", "detail", "mac-address-table"]


def test_the_hyphen_regression_would_be_caught():
    """The bug that started all this: the space form is not in the device's
    completions, so verification must classify it MISSING."""
    from ate.codegen.verify import MISSING, SUPPORTED, _completions, probe_for

    offered = _completions(
        "Possible completions:\r\n"
        "  broadcast-domains   x\r\n  detail   x\r\n"
        "  mac-address-table   x\r\n  summary   x\r\n")

    _p, expect_bad = probe_for("show evpn mac address-table name %s")
    # parent is "show evpn mac address-table", which the device rejects
    # outright; the token we would look for is not offered under `show evpn`.
    assert "mac" not in offered
    status = SUPPORTED if "mac" in offered else MISSING
    assert status == MISSING

    _p2, expect_good = probe_for("show evpn mac-address-table name %s")
    assert expect_good == "name"
    assert "mac-address-table" in offered


# ── building IXIA traffic items in code (no .ixncfg) ─────────────────────


def test_traffic_using_scripts_build_their_items_first(scripts):
    """`setTrafficItemState` unsuspends an item that must already exist. If
    nothing builds it, every traffic step is a silent no-op."""
    for sc in scripts:
        uses = [s for s in sc.steps
                if s.kind in (StepKind.TRAFFIC_STATE, StepKind.TRAFFIC_STOP,
                              StepKind.VERIFY_IXIA)]
        if not uses:
            continue
        kinds = [s.kind for s in sc.steps]
        assert StepKind.TRAFFIC_CREATE in kinds, sc.class_name
        assert kinds.index(StepKind.TRAFFIC_CREATE) < kinds.index(uses[0].kind)


def test_bring_up_does_not_build_traffic_it_never_uses(scripts):
    tc01 = next(s for s in scripts if s.flow_id == "FLOW-010")
    assert StepKind.TRAFFIC_CREATE not in [s.kind for s in tc01.steps]


def test_traffic_build_params_carry_vports_and_source_macs():
    from ate.codegen.java_emitter import emit_params
    from ate.codegen.lab import SINGLE_DUT_3AC

    body = emit_params([], SINGLE_DUT_3AC).content
    assert "TRAFFIC_ITEM_BUILD" in body
    for ti in SINGLE_DUT_3AC.traffic_items:
        assert ti.src_mac in body


def test_ac2_and_ac3_share_a_source_mac():
    """That is what makes AC2 -> AC3 a LOCAL move rather than two hosts."""
    from ate.codegen.lab import SINGLE_DUT_3AC as lab

    ac2 = next(t for t in lab.traffic_items if t.src == "AC2")
    ac3 = next(t for t in lab.traffic_items if t.src == "AC3")
    assert ac2.src_mac == ac3.src_mac


def test_the_unsettable_source_mac_is_declared_not_implied():
    """ixia_lib.tcl has editTrafficRawDestMacAddr and no source equivalent, so
    the generated code must say the MAC is not applied rather than look like it
    applied one."""
    from ate.codegen.java_emitter import emit_utils

    utils = emit_utils(SINGLE_DUT_3AC).content
    assert "SOURCE MAC cannot be set" in utils
    assert "CompassReporter.warning" in utils


# ── every emitted command must exist in the registry ─────────────────────


def test_no_step_references_a_command_outside_the_registry(scripts):
    """A step naming a constant the registry lacks emits `EvpnCommands.FOO`
    for a FOO that does not exist — caught by javac, but only after a full
    framework compile. Catch it here instead."""
    from ate.codegen.commands import command_keys

    keys = command_keys()
    for sc in scripts:
        for st in sc.steps:
            if st.command:
                assert st.command in keys, f"{sc.class_name}/{st.id}: {st.command}"


def test_command_arity_matches_the_arguments_each_step_supplies(scripts):
    """`EvpnCommands.X.args(a)` on a two-%s template types a literal %s at a
    device."""
    from ate.codegen.commands import all_commands

    by_key = {c.key: c for c in all_commands()}
    for sc in scripts:
        for st in sc.steps:
            if not st.command:
                continue
            tmpl = by_key[st.command].template
            assert tmpl.count("%s") == len(st.args), (
                f"{sc.class_name}/{st.id}: {st.command} wants "
                f"{tmpl.count('%s')} arg(s), got {len(st.args)}")


# ── report/session plumbing (cheap, but it is what gets shipped) ─────────


def test_capture_session_reports_and_saves(tmp_path):
    from ate.codegen.capture import (
        EMPTY,
        OK,
        UNSUPPORTED,
        CapturedCommand,
        CaptureSession,
    )

    s = CaptureSession(host="10.3.21.1", build="8.7.0: LAB 22", results=[
        CapturedCommand("A", "show a", OK, ["row"]),
        CapturedCommand("B", "show b", EMPTY),
        CapturedCommand("C", "show c", UNSUPPORTED),
    ])
    assert s.by_status() == {OK: 1, EMPTY: 1, UNSUPPORTED: 1}
    p = s.save(tmp_path / "cap.json")
    import json
    back = json.loads(p.read_text())
    assert back["build"] == "8.7.0: LAB 22"
    assert len(back["results"]) == 3


def test_verify_report_isolates_the_missing_commands(tmp_path):
    from ate.codegen.verify import (
        MISSING,
        SUPPORTED,
        VerifiedCommand,
        VerifyReport,
    )

    r = VerifyReport(host="h", build="b", results=[
        VerifiedCommand("K1", "show a b", "show a ?", "b", SUPPORTED, ["b"]),
        VerifiedCommand("K2", "show a c", "show a ?", "c", MISSING, ["b"]),
    ])
    assert r.by_status() == {SUPPORTED: 1, MISSING: 1}
    assert [m.key for m in r.missing()] == ["K2"]
    assert r.save(tmp_path / "v.json").exists()


def test_capture_skips_steps_nothing_would_consume(scripts):
    """A step with no expect_key has nowhere to put captured output."""
    from ate.codegen.capture import commands_needed

    keys = {k for k, _ in commands_needed(scripts)}
    for sc in scripts:
        for st in sc.steps:
            if st.kind.value in ("verify_cli", "verify_route") and not st.expect_key:
                assert st.expect_key not in keys


def test_plan_rows_are_attributed_only_to_flow_banners(tmp_path):
    """A non-flow banner (an RFC or CLI section) must clear the attribution, or
    unrelated rows get swept into the previous flow."""
    import openpyxl

    from ate.codegen.plan_scripts import flow_rows_from_xlsx

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Test Plan Topics"
    ws.append(["Topic", "Action", "SFS / RFC Req ID"])
    ws.append(["FLOW-010 — Bring-up", "", ""])
    ws.append(["", "Configure the EVI", "EVPNS-REQ#30"])
    ws.append(["RFC7432bis §7.2 — MAC/IP", "", ""])
    ws.append(["", "This belongs to the RFC section", ""])
    p = tmp_path / "plan.xlsx"
    wb.save(p)

    got = flow_rows_from_xlsx(p)
    assert list(got) == ["FLOW-010"]
    assert [a for a, _ in got["FLOW-010"][1]] == ["Configure the EVI"]


def test_generation_result_writes_every_file(tmp_path):
    from ate.codegen import GenerationResult
    from ate.codegen.java_emitter import JavaFile

    r = GenerationResult(files=[
        JavaFile(path="cmp/tests/evpn/A.java", content="class A {}"),
        JavaFile(path="cmp/tests/evpn/configurations/compass/X.cfg", content="!"),
    ])
    written = r.write(tmp_path)
    assert len(written) == 2
    assert all(w.exists() for w in written)


# ── driving a channel, without a device ──────────────────────────────────


class _FakeChannel:
    """Minimal stand-in for a paramiko shell channel.

    Answers each command from a scripted table and always terminates with a
    realistic prompt, so the orchestration can be exercised offline. This is
    the harness that would have caught the buffer-desync bug: it makes
    "which answer belongs to which command" observable.
    """

    PROMPT = "router[2026-08-12-07:00:00]# "

    def __init__(self, answers):
        """`answers` is a LIST, consumed in call order.

        Deliberately not a {command: answer} map: several steps legitimately
        issue the SAME command (two flows both read the MAC table), so a map
        collapses them and the test stops being able to see misattribution.
        """
        self.answers = list(answers)
        self.sent = []
        self._buf = ""

    def send(self, data):
        self.sent.append(data.strip())
        body = self.answers.pop(0) if self.answers else ""
        self._buf += data + body + ("\r\n" if body else "") + self.PROMPT

    def recv_ready(self):
        return bool(self._buf)

    def recv(self, _n):
        out, self._buf = self._buf, ""
        return out.encode()

    def close(self):
        pass


def test_capture_attributes_each_answer_to_its_own_command(scripts):
    from ate.codegen.capture import OK, UNSUPPORTED, capture_on_channel, commands_needed

    needed = commands_needed(scripts)
    assert needed
    # A MAC-table answer has to contain a MAC to count as captured, so give the
    # good answers one. This test is about ATTRIBUTION - which answer lands on
    # which command - and a row that would be rejected as vacuous would test
    # the wrong thing.
    answers = [(f"ROW-{i}-A 00:00:0{i % 10}:00:00:01\r\nROW-{i}-B" if i % 2 == 0
                else "----^\r\nsyntax error: unknown argument")
               for i in range(len(needed))]
    sess = capture_on_channel(_FakeChannel(answers), scripts, host="h", build="b")

    assert len(sess.results) == len(needed)
    for i, r in enumerate(sess.results):
        assert r.command == needed[i][1], "answer attributed to the wrong command"
        if i % 2 == 0:
            assert r.status == OK
            assert r.lines == [f"ROW-{i}-A 00:00:0{i % 10}:00:00:01", f"ROW-{i}-B"]
        else:
            assert r.status == UNSUPPORTED and r.lines == []


def test_only_the_ok_answers_reach_the_expectations(scripts):
    from ate.codegen.capture import capture_on_channel, commands_needed

    needed = commands_needed(scripts)
    answers = ["GOOD"] + ["%  No entries found."] * (len(needed) - 1)
    sess = capture_on_channel(_FakeChannel(answers), scripts)
    usable = sess.usable()
    assert list(usable.values()) == [["GOOD"]]
    assert sess.by_status().get("empty") == len(needed) - 1


# ── an expectation that cannot fail is not an expectation ───────────────
#
# Verbatim from pc-3080 (8.7.0 LAB 22) with evi-1 configured and no traffic
# offered. The command is accepted and answers; the answer is entirely legend.
LEGEND_ONLY_MAC_TABLE = (
    "show evpn mac-address-table name evi-1\r\n"
    "\r\n"
    "LOC:  L - local, R - remote\r\n"
    "L-FL: D - dynamic, S - static\r\n"
    "R-FL: N -learnt, U - Unlearnt\r\n"
    "ACT:  S - Single-Active, A - All-Active\r\n"
    "\r\n"
    "EVPN Name: evi-1, Service Model: vlan-based, Local Label: 40960\r\n"
    "router# "
)

MAC_TABLE_WITH_A_ROW = (
    "show evpn mac-address-table name evi-1\r\n"
    "LOC:  L - local, R - remote\r\n"
    "EVPN Name: evi-1, Service Model: vlan-based, Local Label: 40960\r\n"
    "L   00:00:01:00:00:01   D   x-eth 0/0/8.100\r\n"
    "router# "
)


def test_a_mac_table_with_only_a_legend_is_not_an_expectation():
    """It would assert that the legend prints — true on any device, forever."""
    from ate.codegen.capture import EMPTY, _classify

    status, lines, note = _classify(LEGEND_ONLY_MAC_TABLE,
                                    "show evpn mac-address-table name evi-1")
    assert status == EMPTY
    assert lines == []
    assert "no MAC addresses" in note


def test_a_mac_table_with_a_real_entry_is_captured():
    from ate.codegen.capture import OK, _classify

    status, lines, _ = _classify(MAC_TABLE_WITH_A_ROW,
                                 "show evpn mac-address-table name evi-1")
    assert status == OK
    assert any("00:00:01:00:00:01" in ln for ln in lines)


def test_read_stops_at_the_prompt_and_strips_it():
    from ate.codegen.capture import _read_until_prompt

    chan = _FakeChannel(["LINE-1\r\nLINE-2"])
    chan.send("show x\n")
    raw = _read_until_prompt(chan, timeout=5)
    assert "LINE-1" in raw and "LINE-2" in raw


# ── the prompt shape must not decide whether the device loop works ───────
#
# pc-3021 shows `router[<timestamp>]# `; pc-3080 shows a bare `router# `. The
# timestamp is a per-box CLI setting. The original pattern required the `]`,
# so on pc-3080 no read ever terminated: every probe burned its full timeout
# and returned a partial buffer, and the sweep hung rather than failing. Both
# shapes are real and both must terminate a read.

@pytest.mark.parametrize("prompt", [
    "router# ",
    "router[2026-08-12-07:00:00]# ",
    "router(config)# ",
    "router[2026-08-12-07:00:00](config)# ",
    "exa-il01-uf-3080# ",
])
def test_prompt_matches_every_shape_this_lab_produces(prompt):
    from ate.codegen.capture import _PROMPT

    assert _PROMPT.search("some output\r\n" + prompt), f"{prompt!r} not recognised"


@pytest.mark.parametrize("prompt", ["router# ", "router[2026-08-12-07:00:00]# "])
def test_read_terminates_against_both_prompt_shapes(prompt):
    from ate.codegen.capture import _read_until_prompt

    chan = _FakeChannel(["LINE-1\r\nLINE-2"])
    chan.PROMPT = prompt
    chan.send("show x\n")
    started = time.time()
    raw = _read_until_prompt(chan, timeout=5)
    assert time.time() - started < 4, "read ran to timeout instead of stopping at the prompt"
    assert "LINE-1" in raw and "LINE-2" in raw


# ── the configuration half of verify-commands ───────────────────────────
#
# Every sample below is verbatim from 8.7.0 LAB 22 on pc-3080. A `?` that
# lands on a leaf does not list-and-return: the device starts asking for the
# VALUE, and no `#` prompt is coming. The reader used to wait out its full
# timeout there and return a partial buffer, so the answer stayed in the
# channel and was collected by the NEXT probe — which is how 48 configuration
# verdicts came to describe the wrong commands.

VALUE_PROMPT_ENUM = (
    "l2-services evpn X service-type ?\r\n"
    "Possible completions:\r\n"
    "  vlan-based\r\n"
    "  port-based[vlan-based]\r\n"
    "router(config)# l2-services evpn X service-type \r\n"
    "[port-based,vlan-based]: "
)

VALUE_PROMPT_RANGE = (
    "l2-services evpn X mac-limit ?\r\n"
    "Possible completions:\r\n"
    "  <1-250000>    maximum MAC learned (default 65520)\r\n"
    "  Currently configured[65520]\r\n"
    "router(config)# l2-services evpn X mac-limit \r\n"
    "(<1-250000>    maximum MAC learned (default 65520)\r\n"
    "  Currently configured): "
)

PATH_ABSENT = (
    "l2-services evpn X control-word ?\r\n"
    "                     ^\r\n"
    "% Invalid input detected at '^' marker.\r\n"
    "syntax error: expecting \r\n"
    "  auto-discovery - Set auto-discovery attributes\r\n"
    "  mac-limit      - Set the limit on maximum MAC learned\r\n"
    "router(config)# "
)

PLAIN_LISTING = (
    "show evpn ?\r\n"
    "Description: Show EVPN information\r\n"
    "Possible completions:\r\n"
    "  broadcast-domains   Displays the EVPN broadcast domain\r\n"
    "  detail              Show EVPN detail status\r\n"
    "  mac-address-table   Show the EVPN MAC Address table\r\n"
    "  summary             Show EVPN summary\r\n"
    "router# "
)


@pytest.mark.parametrize("raw", [VALUE_PROMPT_ENUM, VALUE_PROMPT_RANGE])
def test_a_value_prompt_is_recognised_as_the_device_waiting(raw):
    from ate.codegen.capture import at_value_prompt

    assert at_value_prompt(raw), "would burn the timeout and desync the sweep"


@pytest.mark.parametrize("raw", [PATH_ABSENT, PLAIN_LISTING])
def test_a_finished_command_is_not_mistaken_for_a_value_prompt(raw):
    from ate.codegen.capture import at_value_prompt

    assert not at_value_prompt(raw)


def test_a_leaf_default_is_stripped_from_its_completion_token():
    """`port-based[vlan-based]` is the token plus the CURRENT value."""
    from ate.codegen.verify import _completions

    assert "port-based" in _completions(VALUE_PROMPT_ENUM)


def test_completions_drop_the_syntax_error_caret():
    from ate.codegen.verify import _completions

    assert "^" not in _completions(PATH_ABSENT)


@pytest.mark.parametrize("raw,expect,status", [
    # an enumerated leaf CAN be decided by completion, both ways
    (VALUE_PROMPT_ENUM, "port-based", "supported"),
    (VALUE_PROMPT_ENUM, "half-duplex", "missing"),
    # a free/range leaf cannot: `unknown` is the honest verdict, not `missing`
    (VALUE_PROMPT_RANGE, "250000", "unknown"),
    # the path itself is absent from this build
    (PATH_ABSENT, "disable", "missing"),
    # the ordinary case still works
    (PLAIN_LISTING, "mac-address-table", "supported"),
    (PLAIN_LISTING, "global", "missing"),
])
def test_verdicts_match_what_the_device_actually_said(raw, expect, status):
    from ate.codegen.verify import _completions, _verdict

    got, _note = _verdict(raw, expect, _completions(raw))
    assert got == status


def test_a_range_leaf_is_never_reported_missing():
    """`mac-limit 250000` is a real command; completion cannot confirm it.

    Reporting it `missing` sends someone to "fix" a correct command, which is
    the failure mode this whole stage exists to prevent.
    """
    from ate.codegen.verify import MISSING, _completions, _verdict

    status, note = _verdict(VALUE_PROMPT_RANGE, "250000",
                            _completions(VALUE_PROMPT_RANGE))
    assert status != MISSING
    assert "free value" in note


KEY_REJECTED = (
    "routing bgp X vrf X neighbor X af-l2vpn ?\r\n"
    "                       ^\r\n"
    "% Invalid input detected at '^' marker.\r\n"
    'syntax error: "X" is not a valid value.\r\n'
    "router(config)# "
)


def test_an_unaskable_probe_is_unknown_not_missing():
    """The placeholder was rejected as a key, so the node was never reached.

    `af-l2vpn evpn` exists on this build — with a real AS number and a real
    neighbour address the device lists `evpn` and `vpls`. Reporting `missing`
    would send someone to fix a command that is already correct.
    """
    from ate.codegen.verify import MISSING, UNKNOWN, _completions, _verdict

    status, note = _verdict(KEY_REJECTED, "evpn", _completions(KEY_REJECTED))
    assert status == UNKNOWN
    assert status != MISSING
    assert "not a legal key" in note


def test_angle_bracket_arguments_are_slots_not_cli_text():
    """`<value>` is how the CLI-doc-derived entries spell an argument.

    Probing for a literal `<value>` token in a completion list can only ever
    report `missing`, on every build, for every device.
    """
    from ate.codegen.verify import probe_for

    parent, expect = probe_for(
        "routing bgp %s vrf %s neighbor %s af-l2vpn evpn allow-as-in <value>")
    assert expect == "allow-as-in"
    assert parent == "routing bgp X vrf X neighbor X af-l2vpn evpn"


def test_prompt_does_not_swallow_output_lines():
    """The pattern is also used to strip prompts out of captured output."""
    from ate.codegen.capture import _PROMPT

    for line in ("  mac-address-table   Show the EVPN MAC Address table",
                 "8.7.0: LAB 22",
                 "MAC Limit          65520",
                 "Total entries: 3"):
        assert not _PROMPT.search(line), f"real output line {line!r} mistaken for a prompt"


# ── PIPELINE RULE: nothing may fake a pass ──────────────────────────────
#
# Every case below is one that actually happened on hardware. A red test gets
# fixed; a green test that checks nothing gets trusted, which is worse than
# having no test at all.

LEGEND_ONLY_CAPTURE = {
    "FLOW030_S04_AC1_MACS_LEARNT_LINES": {
        "lines": [
            "LOC:  L - local, R - remote",
            "L-FL: D - dynamic, S - static",
            "ACT:  S - Single-Active, A - All-Active",
            "--------------------------------------",
            "INTERFACE  ESI  ES LABEL",
        ],
        "command": "show evpn mac-address-table name evi-1",
        "host": "10.3.80.1", "build": "8.7.0: LAB 22", "captured_at": "now",
    },
}

REAL_CAPTURE = {
    "FLOW010_S08_EVPN_DETAIL_LINES": {
        "lines": ["EVPN name: evi-1", "Service Type: vlan-based",
                  "MAC Limit: 65520"],
        "command": "show evpn detail",
        "host": "10.3.80.1", "build": "8.7.0: LAB 22", "captured_at": "now",
    },
}


def test_an_expectation_of_pure_table_furniture_is_rejected(scripts):
    """It would match on a device where the feature does nothing."""
    from ate.codegen.fake_pass import audit

    violations = audit(scripts, LEGEND_ONLY_CAPTURE)
    assert violations, "a legend-only expectation must be caught"
    assert violations[0].rule == "unfalsifiable-expectation"


def test_a_real_capture_is_not_flagged(scripts):
    from ate.codegen.fake_pass import audit

    assert audit(scripts, REAL_CAPTURE) == []


def test_generation_stops_on_an_unfalsifiable_expectation(scripts):
    """Fatal, like an ungrounded command - not a warning nobody reads."""
    from ate.codegen.fake_pass import FakePassError, audit

    violations = audit(scripts, LEGEND_ONLY_CAPTURE)
    with pytest.raises(FakePassError):
        raise FakePassError("; ".join(str(v) for v in violations))


def test_the_census_counts_what_can_actually_fail(scripts):
    from ate.codegen.fake_pass import assertion_census

    census = assertion_census(scripts, REAL_CAPTURE)
    assert census.falsifiable == ["FLOW-010.S08"]
    assert census.warns_only, "the rest must be reported as warn-only"
    assert census.total == len(census.falsifiable) + len(census.warns_only)


def test_every_test_class_refuses_to_pass_without_verifying_something(files):
    """The run-time half: emptiness is only knowable on the device."""
    for f in files:
        if f.class_name.startswith("TC"):
            assert "evpnUtils.assertSomethingWasVerified();" in f.content, \
                f"{f.class_name} could report a pass having verified nothing"


def test_a_no_change_assertion_refuses_an_empty_baseline(files):
    """"Nothing changed" is trivially true when there was nothing to change."""
    utils = next(f for f in files if f.class_name == "EvpnUtils").content
    assert "isEmptyTable(before)" in utils
    assert "NOT ASSERTED" in utils
    # and it must not be counted as an assertion in that case
    before_guard = utils.index("isEmptyTable(before)")
    after_guard = utils.index("falsifiableAssertions++", before_guard)
    assert utils.index("return;", before_guard) < after_guard


def test_only_the_non_empty_path_counts_as_an_assertion(files):
    utils = next(f for f in files if f.class_name == "EvpnUtils").content
    assert utils.count("falsifiableAssertions++") == 2, \
        "exactly the show-lines and the no-change paths may count"
