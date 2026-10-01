"""Pipeline rule: review every generated step the way the client's expert does.

`fake_pass.py` asks "can this step fail at all?". This module asks the
harder question a domain reviewer asks: "would this step fail if the FEATURE
were broken?". A step can be perfectly falsifiable and still prove nothing
about EVPN: it fails if the rig is broken, and passes whether or not the
feature works.

Every rule below is a finding a client reviewer made by reading our report,
turned into a check that runs before any Java is written. The client should
never have to find the same class of defect twice.

| Rule | Found by, when |
|---|---|
| claims-advertisement-reads-local-table | Eyal, 2026-09-30, TC02 step 23 |
| unicast-claim-on-flooded-traffic | Eyal, 2026-09-30, TC02 step 17 |
| rate-above-tx-not-asserted-as-flooding | Eyal, 2026-09-30, TC02 step 27 |
| shared-port-without-per-circuit-proof | Eyal, 2026-09-30, TC02 step 27 |
| traffic-state-contradiction | 2026-09-09, suite-wide "all running" rows |
| absence-without-prior-presence | 2026-09-09, TC03 aged out MACs never learnt |
| presence-without-stimulus | Eyal, 2026-09-30, TC03 step 17 |
| split-commit | Eyal, 2026-09-30, TC01 steps 3 to 8 |
| title-apologises-for-rig | 2026-08-16, TC01 "(no BGP peer on this rig)" |
| title-names-placeholder-interface | Eyal, 2026-09-30, TC01 steps 6 to 8 |
| title-keyword-not-performed | Eyal, 2026-09-30, TC01 step 4 |

Like the fake-pass rule there is no override. If a rule is wrong for a real
step, fix the rule and add the case to its test, so the reason is recorded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ate.codegen.lab import LabProfile
from ate.codegen.script_ir import Step, StepKind, TestScript

__all__ = ["DomainReviewError", "Finding", "review"]

_VERIFY = (StepKind.VERIFY_CLI, StepKind.VERIFY_ROUTE, StepKind.VERIFY_IXIA)
_MAC = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", re.IGNORECASE)
_ROUTE_CLAIM = re.compile(r"\badvertis\w*\b.*\b(type-\d|route)\b|"
                          r"\b(type-\d|route)\b.*\badvertis", re.IGNORECASE)
_UNICAST_CLAIM = re.compile(r"\bunicast\b", re.IGNORECASE)
_KNOWN_CLAIM = re.compile(r"\bknown unicast\b|\bonly\b|\bfollows\b",
                          re.IGNORECASE)
_FLOOD_CLAIM = re.compile(r"\bflood", re.IGNORECASE)
_GONE_CLAIM = re.compile(r"\b(aged|withdrawn|removed|deleted|gone|"
                         r"no longer|flushed)\b", re.IGNORECASE)
_APOLOGY = re.compile(r"\bon this rig\b|\bno bgp peer\b|\bnot supported\b|"
                      r"\bworkaround\b|\bcannot\b|\bTODO\b|\bknown limitation",
                      re.IGNORECASE)
_CLI_KEYWORD = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b")


@dataclass
class Finding:
    step_id: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.step_id} [{self.rule}] {self.detail}"


class DomainReviewError(RuntimeError):
    """A generated step would pass on a device where the feature is broken."""


def _is_broadcast_or_multicast(mac: str) -> bool:
    return int(mac.split(":")[0], 16) & 1 == 1


def _commands(st: Step) -> list[str]:
    return [st.command, *(c for c, _ in st.more)] if st.command else []


def _args(st: Step) -> list[str]:
    return [*st.args, *(a for _, args in st.more for a in args)]


def _same_table(a: str, b: str) -> bool:
    """One command is the other with a narrowing filter (`..._SOURCE_$`)."""
    return a.startswith(b) or b.startswith(a)


def _subjects(st: Step) -> set[str]:
    """What a verification step is about: its MACs, else its literals."""
    text = " ".join(st.expect_literal) + " " + st.expect_subject
    macs = {m.lower() for m in _MAC.findall(text)}
    return macs or set(st.expect_literal)


def _review_script(sc: TestScript, lab: LabProfile,
                   vocab: set[str]) -> list[Finding]:
    out: list[Finding] = []
    items = {ti.name: ti for ti in lab.traffic_items}
    acs = {ac.name: ac for ac in lab.acs}
    by_iface = {ac.ac_interface: ac for ac in lab.acs}
    vport_users: dict[str, list[str]] = {}
    for ac in lab.acs:
        vport_users.setdefault(ac.vport, []).append(ac.name)
    placeholders = {ac.interface for ac in lab.acs}

    enabled: set[str] = set()
    ever_enabled: set[str] = set()
    presence: list[Step] = []
    prev: Step | None = None

    def add(st: Step, rule: str, detail: str) -> None:
        out.append(Finding(st.id, rule, detail))

    for st in sc.steps:
        if st.todo:
            prev = st
            continue

        # Titles: what the reviewer reads first.
        if _APOLOGY.search(st.text):
            add(st, "title-apologises-for-rig",
                "the title excuses the testbed; fix the rig or drop the step")
        for ph in placeholders:
            if re.search(rf"\b{re.escape(ph)}\b", st.text):
                add(st, "title-names-placeholder-interface",
                    f"title names {ph!r}, a lab placeholder the SUT rebinds; "
                    "name the circuit and VLAN instead")
        cmds = _commands(st)
        if cmds:
            args = " ".join(_args(st)).lower()
            for kw in sorted(set(_CLI_KEYWORD.findall(st.text))):
                key = kw.upper().replace("-", "_")
                if (any(key in v for v in vocab)
                        and not any(key in c for c in cmds)
                        and kw not in args):
                    add(st, "title-keyword-not-performed",
                        f"title says {kw!r} but no command in the step uses it")

        # One change, one commit.
        if (st.kind is StepKind.CONFIG and prev is not None
                and prev.kind is StepKind.CONFIG and not prev.todo):
            add(st, "split-commit",
                f"follows CONFIG step {prev.id} with nothing verified "
                "between; stage both lines in one commit (Step.more)")

        # Traffic state, as the steps leave it.
        if st.kind is StepKind.TRAFFIC_STATE:
            for name in st.traffic_items:
                if st.enabled:
                    enabled.add(name)
                    ever_enabled.add(name)
                else:
                    enabled.discard(name)

        # "Advertised" must be read off what was sent to a peer.
        if (st.kind in _VERIFY and _ROUTE_CLAIM.search(st.text)
                and not any("ADVERTISED" in c for c in cmds)):
            add(st, "claims-advertisement-reads-local-table",
                f"title claims an advertised route but reads {st.command}; "
                "read the routes sent to the peer, or say 'originated'")

        if st.kind is StepKind.VERIFY_IXIA:
            out += _review_traffic(st, items, acs, vport_users, enabled)

        # Absence after an event must follow proof of presence.
        if (st.kind in _VERIFY and st.expect_absent
                and _GONE_CLAIM.search(st.text)):
            subj = _subjects(st)
            seen = any(_same_table(p.command, st.command)
                       and _subjects(p) & subj for p in presence)
            if not seen:
                add(st, "absence-without-prior-presence",
                    f"asserts {sorted(subj)} gone via {st.command} but no "
                    "earlier step showed it present with that command; on a "
                    "device that never had it this passes")

        # A learnt MAC needs traffic that sources it, from that circuit.
        if (st.kind in (StepKind.VERIFY_CLI, StepKind.VERIFY_ROUTE)
                and not st.expect_absent):
            macs = {m.lower() for m in _MAC.findall(" ".join(st.expect_literal))}
            for mac in sorted(macs):
                srcs = [items[n] for n in ever_enabled
                        if n in items and items[n].src_mac.lower() == mac]
                ifaces = [a for a in st.args if a in by_iface]
                if ifaces:
                    want = by_iface[ifaces[0]].name
                    srcs = [t for t in srcs if t.src == want]
                if not srcs:
                    where = f" on {by_iface[ifaces[0]].name}" if ifaces else ""
                    add(st, "presence-without-stimulus",
                        f"expects {mac}{where} but no traffic item sourcing it "
                        "from there was started earlier; a pass would be "
                        "another circuit's state")
            if st.kind in _VERIFY:
                presence.append(st)
        prev = st
    return out


def _review_traffic(st: Step, items: dict, acs: dict,
                    vport_users: dict[str, list[str]],
                    enabled: set[str]) -> list[Finding]:
    out: list[Finding] = []

    def add(rule: str, detail: str) -> None:
        out.append(Finding(st.id, rule, detail))

    for name, tx, rx in st.expect_rows:
        ti = items.get(name)
        if ti is None:
            continue
        try:
            tx_n, rx_n = int(tx), int(rx)
        except ValueError:
            continue
        if tx_n > 0 and name not in enabled:
            add("traffic-state-contradiction",
                f"expects {name} transmitting but it is not started here")
        if tx_n == 0 and name in enabled:
            add("traffic-state-contradiction",
                f"expects {name} silent but it was started and not stopped")
        if tx_n == 0:
            continue
        flooded = _is_broadcast_or_multicast(ti.dst_mac)
        if flooded and _UNICAST_CLAIM.search(st.text):
            add("unicast-claim-on-flooded-traffic",
                f"title claims unicast but {name} is sent to {ti.dst_mac}, "
                "which floods whatever the MAC table holds")
        if flooded and _KNOWN_CLAIM.search(st.text):
            add("unicast-claim-on-flooded-traffic",
                f"title claims delivery to one circuit but {name} is "
                f"broadcast; forwarding cannot change when a MAC is learnt")
        if rx_n > tx_n:
            if not _FLOOD_CLAIM.search(st.text) or len(st.egress_on) < 2:
                add("rate-above-tx-not-asserted-as-flooding",
                    f"{name} expects rx {rx} above tx {tx}, which is "
                    "flooding; the title must say so and egress_on must "
                    "name every circuit it floods to")
        dst = acs.get(ti.dst)
        if (rx_n > 0 and dst is not None
                and len(vport_users.get(dst.vport, [])) > 1
                and not (st.egress_on or st.egress_silent)):
            add("shared-port-without-per-circuit-proof",
                f"{name} is received on {dst.vport}, shared by "
                f"{vport_users[dst.vport]}; the tester's counter cannot say "
                "which circuit carried it, so assert DUT egress per circuit")
    return out


def review(scripts: list[TestScript], lab: LabProfile) -> list[Finding]:
    """Every step a domain expert would reject, across the whole suite."""
    from ate.codegen.commands import command_keys  # noqa: PLC0415

    vocab = command_keys()
    out: list[Finding] = []
    for sc in scripts:
        out += _review_script(sc, lab, vocab)
    return out
