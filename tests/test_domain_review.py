"""The domain-review gate: each rule is a defect a client reviewer found."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ate.codegen.domain_review import review
from ate.codegen.evpn_scripts import evpn_scripts
from ate.codegen.lab import (
    SINGLE_DUT_2AC_CORE,
    SINGLE_DUT_3AC,
    SINGLE_DUT_3AC_CORE,
    TrafficItem,
)
from ate.codegen.script_ir import Step, StepKind, TestScript

LAB = SINGLE_DUT_3AC_CORE
MAC1 = "00:00:01:00:00:01"
MAC2 = "00:00:02:00:00:01"
TABLE = "SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$"
BY_SOURCE = "SHOW_EVPN_MAC_ADDRESS_TABLE_NAME_$_SOURCE_$"
ADV = "SHOW_BGP_L2VPN_EVPN_NEIGHBORS_ADVERTISED_ROUTES_$_DETAIL"
LOCAL = "SHOW_BGP_L2VPN_EVPN_TABLE_EVI_DETAIL"


def _rules(steps: list[Step], lab=LAB) -> set[str]:
    sc = TestScript(flow_id="FLOW-999", class_name="TC99", method_name="t",
                    title="t", summary="t", steps=steps)
    return {f.rule for f in review([sc], lab)}


def _start(*items: str, sid: str = "S01") -> Step:
    return Step(id=sid, kind=StepKind.TRAFFIC_STATE, text="Start traffic",
                traffic_items=list(items), enabled=True)


def _ixia(text: str, rows, on=(), silent=()) -> Step:
    return Step(id="S10", kind=StepKind.VERIFY_IXIA, text=text,
                expect_rows=list(rows), egress_on=list(on),
                egress_silent=list(silent))


@pytest.mark.parametrize("lab", [SINGLE_DUT_3AC_CORE, SINGLE_DUT_2AC_CORE,
                                 SINGLE_DUT_3AC])
def test_curated_suites_pass_the_review(lab):
    assert review(evpn_scripts(lab), lab) == []


def test_advertised_claim_on_the_local_table_is_rejected():
    st = Step(id="S01", kind=StepKind.VERIFY_ROUTE, command=LOCAL,
              text=f"Verify the Type-2 route for {MAC1} is advertised",
              expect_literal=["Type=2"])
    assert "claims-advertisement-reads-local-table" in _rules([st])
    ok = st.model_copy(update={"command": ADV})
    assert "claims-advertisement-reads-local-table" not in _rules([ok])


def test_unicast_claim_on_broadcast_traffic_is_rejected():
    bcast = replace(LAB, traffic_items=[
        TrafficItem(name="TI_AC1_TO_AC2", src="AC1", dst="AC2", src_mac=MAC1)])
    steps = [_start("TI_AC1_TO_AC2"),
             _ixia("Verify known unicast to AC2 only",
                   [("TI_AC1_TO_AC2", "1000", "1000")], on=["AC2"],
                   silent=["AC3"])]
    assert "unicast-claim-on-flooded-traffic" in _rules(steps, bcast)
    assert "unicast-claim-on-flooded-traffic" not in _rules(steps)


def test_rx_above_tx_must_be_asserted_as_flooding():
    steps = [_start("TI_AC1_TO_AC2"),
             _ixia("Verify AC1 -> AC2 is forwarded",
                   [("TI_AC1_TO_AC2", "1000", "2000")], on=["AC2"])]
    assert "rate-above-tx-not-asserted-as-flooding" in _rules(steps)
    steps[1] = _ixia("Verify AC1 -> AC2 is flooded to AC2 and AC3",
                     [("TI_AC1_TO_AC2", "1000", "2000")], on=["AC2", "AC3"])
    assert "rate-above-tx-not-asserted-as-flooding" not in _rules(steps)


def test_shared_port_needs_per_circuit_egress():
    steps = [_start("TI_AC1_TO_AC2"),
             _ixia("Verify AC1 -> AC2 arrives",
                   [("TI_AC1_TO_AC2", "1000", "1000")])]
    assert "shared-port-without-per-circuit-proof" in _rules(steps)


def test_rows_must_match_the_traffic_that_is_running():
    rows = [("TI_AC1_TO_AC2", "1000", "1000"), ("TI_AC2_TO_AC1", "0", "0")]
    steps = [_start("TI_AC2_TO_AC1"),
             _ixia("Verify AC1 -> AC2", rows, on=["AC2"], silent=["AC3"])]
    assert "traffic-state-contradiction" in _rules(steps)


def test_aged_out_needs_the_mac_shown_present_first():
    gone = Step(id="S05", kind=StepKind.VERIFY_CLI, command=TABLE,
                text=f"Verify {MAC2} has aged out", expect_literal=[MAC2],
                expect_absent=True)
    assert "absence-without-prior-presence" in _rules([gone])
    present = Step(id="S02", kind=StepKind.VERIFY_CLI, command=BY_SOURCE,
                   args=["evi-1", LAB.ac("AC2").ac_interface],
                   text=f"Verify {MAC2} is learnt on AC2",
                   expect_literal=[MAC2 + r"\s+L\s"])
    steps = [_start("TI_AC2_TO_AC1"), present, gone]
    assert "absence-without-prior-presence" not in _rules(steps)


def test_a_baseline_absence_is_not_an_aging_claim():
    st = Step(id="S00", kind=StepKind.VERIFY_CLI, command=TABLE,
              text="Verify the MAC table has no learnt MAC yet",
              expect_literal=[MAC2], expect_absent=True)
    assert _rules([st]) == set()


def test_a_learnt_mac_needs_traffic_from_that_circuit():
    learnt = Step(id="S05", kind=StepKind.VERIFY_CLI, command=BY_SOURCE,
                  args=["evi-1", LAB.ac("AC2").ac_interface],
                  text=f"Verify {MAC2} is learnt on AC2",
                  expect_literal=[MAC2 + r"\s+L\s"])
    # TC03 step 17: only AC1 was started, so the table held AC1's MAC.
    assert "presence-without-stimulus" in _rules([_start("TI_AC1_TO_AC2"),
                                                  learnt])
    # AC3 sources the same MAC, but the step asks about AC2.
    assert "presence-without-stimulus" in _rules([_start("TI_AC3_TO_AC1"),
                                                  learnt])
    assert "presence-without-stimulus" not in _rules([_start("TI_AC2_TO_AC1"),
                                                      learnt])


def test_two_commits_in_a_row_are_one_change():
    a = Step(id="S01", kind=StepKind.CONFIG, text="Set import-rt",
             command="CONFIGURE_L2_SERVICES_EVPN_$_IMPORT_RT_$")
    b = Step(id="S02", kind=StepKind.CONFIG, text="Set export-rt",
             command="CONFIGURE_L2_SERVICES_EVPN_$_EXPORT_RT_$")
    assert "split-commit" in _rules([a, b])


def test_titles_do_not_apologise_or_name_placeholders():
    st = Step(id="S01", kind=StepKind.VERIFY_CLI, command=TABLE,
              text="Verify the table on agg-eth-2 (no BGP peer on this rig)",
              expect_literal=[MAC2])
    rules = _rules([st])
    assert "title-apologises-for-rig" in rules
    assert "title-names-placeholder-interface" in rules


def test_title_keywords_must_be_performed():
    # TC01 step 4: the title said import and export, the step did import only.
    st = Step(id="S01", kind=StepKind.CONFIG,
              text="Configure import-rt and export-rt 65000:1",
              command="CONFIGURE_L2_SERVICES_EVPN_$_IMPORT_RT_$",
              args=["evi-1", "65000:1"])
    assert "title-keyword-not-performed" in _rules([st])
    st.more = [("CONFIGURE_L2_SERVICES_EVPN_$_EXPORT_RT_$", ["evi-1", "65000:1"])]
    assert "title-keyword-not-performed" not in _rules([st])
