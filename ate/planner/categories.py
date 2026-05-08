"""Test plan categories and per-(tag, category) action templates.

Three pieces of logic live here:

1. **Applicability matrix** (TAG_TO_CATEGORIES): which Categories are relevant
   for a requirement given its domain tags. We don't apply every Category to
   every requirement — that's how v1 produced 960 rows of generic boilerplate.

2. **Generic action templates** (CATEGORY_ACTIONS): per-Category action +
   expectation pairs. Templates use {title}, {req_id}, {section},
   {must_hint}, {rfc_refs_or_rfc7432bis}, {cli_hint}, {neighbor_feature}.
   Every action_steps body is rendered with the Setup/Action/Verify
   scaffolding so QA can follow the row without asking what to set up
   first or what counts as "pass" — closes Yossi's gap on missing steps.

3. **RFC content-aware overrides** (rfc_actions_for): for an RFC-derived
   requirement we dispatch on title/keywords (route type N, DF election,
   MAC mobility, label allocation, ESI, BUM, aliasing, …) and emit
   conformance rows that reference the actual RFC mechanism rather than
   a generic "exercise §X" wrapper.

Categories mirror references/Feature Name Test Plan Template.xlsx.
"""
from __future__ import annotations

# All categories from the xlsx template, in stable order.
ALL_CATEGORIES: list[str] = [
    "CLI configuration",
    "Basic Functionality",
    "On The Fly changes",
    "Packet validation",
    "Malformed/unsupported packets",
    "Feature interaction",
    "3rd Party Interoperability",
    "Scale",
    "Performance",
    "Robustness",
    "PM",
    "Alarms/Logs/Syslog",
    "Upgrade",
    "HA",
    "Long run",
    "Management",
    "Tech-support",
]

# Domain-tag → relevant Categories. Multi-tag requirements get the union.
TAG_TO_CATEGORIES: dict[str, list[str]] = {
    "CONFIG": [
        "CLI configuration", "Basic Functionality", "On The Fly changes",
        "Upgrade", "Management",
    ],
    "PACKET": [
        "Basic Functionality", "Packet validation",
        "Malformed/unsupported packets", "Feature interaction",
        "Performance",
    ],
    "HA": [
        "Basic Functionality", "Robustness", "HA", "Long run",
        "Feature interaction", "3rd Party Interoperability",
    ],
    "SCALE": [
        "Scale", "Performance", "Long run",
    ],
    "PROTOCOL": [
        "Basic Functionality", "3rd Party Interoperability",
        "Packet validation", "Feature interaction",
    ],
    "MONITORING": [
        "Alarms/Logs/Syslog", "PM", "Tech-support",
    ],
    # META = no domain match. Minimal coverage so we still emit *something*
    # but don't pretend "Configure RFC support via CLI" is a meaningful test.
    "META": [
        "Basic Functionality", "3rd Party Interoperability",
    ],
}

# Categories ALWAYS applied to every requirement (regardless of tags).
ALWAYS_CATEGORIES: list[str] = ["Tech-support"]

# Categories that don't make sense for an RFC-derived requirement.
# RFCs define protocol behavior — they don't specify CLI, NETCONF management,
# or vendor upgrade mechanics. Applying these categories to an RFC clause
# produces nonsense rows like "Configure Ethernet Segment via NETCONF" for
# RFC7432bis-§5, where §5 is a conceptual chapter, not a configurable feature.
RFC_EXCLUDED_CATEGORIES: set[str] = {
    "CLI configuration",
    "On The Fly changes",
    "Upgrade",
    "Management",
}


def _scaffold(setup: str, action: str, verify: str) -> str:
    """Render the Setup/Action/Verify scaffolding into a single multi-line
    cell value. Yossi's "steps and expected results not defined" gap.
    """
    return (
        f"Setup:  {setup}\n"
        f"Action: {action}\n"
        f"Verify: {verify}"
    )


def _expect(pass_: str, fail_on: str = "") -> str:
    """Render an Expectation with measurable Pass / Fail-on lines."""
    if fail_on:
        return f"Pass:    {pass_}\nFail-on: {fail_on}"
    return f"Pass:    {pass_}"


# --- Generic per-Category templates ─────────────────────────────────────────
# Per-Category: list of (action_template, expectation_template) pairs.
# Templates may use the placeholders:
#   {title}, {req_id}, {section}, {must_hint}, {rfc_refs_or_rfc7432bis},
#   {cli_hint}, {rfc_hint}, {neighbor_feature}
# Multiple pairs per Category produce multiple rows per applicable requirement.
CATEGORY_ACTIONS: dict[str, list[tuple[str, str]]] = {
    "CLI configuration": [
        # NOTE: when a CLI doc is wired into the generator, command-specific
        # rows from cli_rows.py replace these generic ones. These remain as
        # a fallback for spec requirements that don't map to a CLI command.
        (_scaffold(
            "DUT booted, no prior config for {title}.",
            "Configure {title} {section}{cli_hint}; commit; save running-config; reload.",
            "After reload, `show running-config` shows the {title} config; "
            "feature reads back via its `show` command without errors."),
         _expect(
            "Configuration accepted, persists across reload, visible in `show running-config`",
            "Commit error, lost-on-reload, or feature fails to come up{must_hint}")),
        (_scaffold(
            "{title} configured per the canonical example.",
            "Edit one parameter of the configuration; commit.",
            "Edit applied; `show running-config` reflects the change; feature "
            "reconverges without flap."),
         _expect("Edit applied; `show running-config` reflects the change",
                 "Commit rejected, partial-apply, or service flap on edit")),
        (_scaffold(
            "{title} configured.",
            "Issue `no` form of the configuration; commit.",
            "Configuration removed; related show commands report empty/default."),
         _expect("Configuration removed; show commands report empty/default",
                 "Stale state in show commands or kernel forwarding tables")),
        (_scaffold(
            "{title} configured; saved as a candidate.",
            "Apply factory-default; replay the saved configuration.",
            "After replay the configuration is identical (`diff` on saved configs)."),
         _expect("After replay the configuration is byte-identical",
                 "Commit fails or `diff` shows drift")),
        (_scaffold(
            "{title} configured.",
            "Trigger rollback after a configuration change.",
            "Previous configuration restored; service uninterrupted; "
            "rollback-event recorded in `show log`."),
         _expect("Previous configuration restored without service disruption",
                 "Service flap or stale config after rollback")),
    ],
    "Basic Functionality": [
        (_scaffold(
            "Single-router topology with {title} configured per spec {section}.",
            "Bring the feature into its operational state and exercise the "
            "happy path described in {section}{rfc_hint}.",
            "Feature behaves per requirement; counters increment; relevant "
            "show commands reflect normal state."),
         _expect("Feature behaves per requirement{must_hint}",
                 "Counters frozen, show commands report error, or traffic black-holed")),
        (_scaffold(
            "{title} present in the spec but not configured on DUT.",
            "Trigger the feature without explicit configuration; observe "
            "the system's default behavior.",
            "System falls back to documented default; no spurious alarms; "
            "no crash."),
         _expect("System falls back to documented default; no spurious alarms",
                 "Feature partially active without configuration, or default differs from spec")),
    ],
    "On The Fly changes": [
        (_scaffold(
            "{title} configured; IXIA traffic flowing through DUT for ≥ 1 minute.",
            "Modify the {title} configuration while traffic flows (e.g. change "
            "a parameter, then change it back).",
            "IXIA reports zero loss during the change; "
            "`show running-config` reflects the new value within ≤ 1 s."),
         _expect("Modification applied without service interruption{must_hint}",
                 "Traffic loss > 0 packets, or new config not active within 1 s")),
    ],
    "Packet validation": [
        (_scaffold(
            "{title} fully configured; BGP EVPN session up to neighbor PE.",
            "Send valid traffic exercising {title} from IXIA — capture both "
            "the PE↔PE BGP EVPN routes and the access-side data frames.",
            "Frames forwarded as expected; counters increment; received "
            "BGP EVPN routes match the expected encoding{must_hint}."),
         _expect("Traffic forwarded; counters increment; route encoding matches",
                 "Unexpected drops, miscounted forwards, or malformed BGP EVPN routes on the wire")),
    ],
    "Malformed/unsupported packets": [
        (_scaffold(
            "{title} configured; IXIA primed with a fault-injection script.",
            "Inject malformed/unsupported variants of {title} traffic "
            "(bad TLV length, reserved bits set, oversized fields).",
            "Variants dropped at ingress; no crash; error counter "
            "increments; syslog records the event."),
         _expect("Variants dropped; no crash; error counter increments; syslog entry present",
                 "Crash, stale state, missing syslog, or malformed packet propagated to peer")),
    ],
    "Feature interaction": [
        (_scaffold(
            "{title} configured alongside {neighbor_feature} on the same DUT.",
            "Exercise both features simultaneously under traffic.",
            "Both features operate per spec; no regression in either's "
            "show commands or counters{must_hint}."),
         _expect("Both features operate per spec; no regression",
                 "Either feature breaks, counters stop, or one masks the other")),
    ],
    "3rd Party Interoperability": [
        (_scaffold(
            "Exaware DUT + 3rd-party PE (Cisco/Juniper) connected over MPLS; "
            "BGP EVPN session established.",
            "Bring up {title} per {rfc_refs_or_rfc7432bis} on both sides; "
            "exchange routes and frames.",
            "Both PEs accept each other's encoding; routes installed in "
            "FIB; data plane forwards bidirectionally."),
         _expect("Interop succeeds; routes/frames exchanged correctly per RFC",
                 "Route rejected, encoding mismatch, or one-way black-hole")),
    ],
    "Scale": [
        (_scaffold(
            "Two-PE topology with {title} configured to documented system limit "
            "(check `show evpn summary` for the limit number).",
            "Scale {title} to the documented maximum (advertise/install at the "
            "spec-defined ceiling); hold for ≥ 5 minutes.",
            "Limit reached without crash; CPU and memory remain in green band; "
            "convergence on incremental change is unchanged from baseline."),
         _expect("Limit reached; performance and stability remain within bounds",
                 "Crash, OOM, or per-route convergence > 2× baseline at scale")),
    ],
    "Performance": [
        (_scaffold(
            "Two-PE topology with {title} configured; IXIA scale rig generating "
            "documented load profile.",
            "Measure {title} throughput / latency / convergence under "
            "documented load.",
            "All metrics within the bounds defined by the spec/SLA; "
            "report numeric pass/fail per metric."),
         _expect("All metrics within spec/SLA bounds (numeric)",
                 "Any metric outside the SLA — must be reported as a fail, not soft-met")),
    ],
    "Robustness": [
        (_scaffold(
            "{title} active on DUT; IXIA generating background traffic.",
            "Reset the Exaware control-plane process while {title} is active "
            "(use platform reset CLI).",
            "Feature recovers automatically; data-path remains "
            "forwarding (no full outage); convergence ≤ documented value."),
         _expect("Feature recovers automatically; data-path stays up",
                 "Full outage > 1 s, no auto-recovery, or feature stuck after recovery")),
        (_scaffold(
            "{title} active on DUT.",
            "Power-cycle the Exaware while {title} is active "
            "(use the lab PDU / smart-PSU harness).",
            "After full boot, feature recovers; configuration intact; "
            "BGP EVPN session re-establishes."),
         _expect("Feature recovers after power-cycle; configuration intact",
                 "Lost config, failed BGP re-establishment, or partial recovery")),
        (_scaffold(
            "{title} active on DUT; traffic flowing.",
            "Flap the relevant interface while {title} is active.",
            "Feature recovers; convergence within fast-convergence bounds "
            "(per [RFC7432bis] §8 mass-withdrawal)."),
         _expect("Feature recovers; convergence within fast-convergence bounds",
                 "Convergence above documented bound or stale FIB after flap")),
    ],
    "PM": [
        (_scaffold(
            "{title} active on DUT; reference traffic load applied.",
            "Read PM counters relevant to {title} (e.g. `show evpn mac "
            "address-table`, per-EVI counters); clear; re-read; reload.",
            "Counters increment correctly; clear works; values persist "
            "across reload as documented."),
         _expect("Counters increment, clear works, persistence per spec",
                 "Counter freezes, clear no-op, or persistence broken")),
    ],
    "Alarms/Logs/Syslog": [
        (_scaffold(
            "{title} configured; syslog destination set; an alarm condition "
            "primed (e.g. mac-limit, peer flap, misconfig).",
            "Trigger the error condition for {title}; observe `show alarms` "
            "and the syslog feed.",
            "Alarm raised at the right severity; syslog entry generated "
            "with structured fields; alarm clears when condition is resolved."),
         _expect("Alarm raised, syslog generated, alarm clears on resolution",
                 "No alarm, wrong severity, missing syslog, or stuck alarm")),
    ],
    "Upgrade": [
        (_scaffold(
            "DUT with {title} configured on current image; upgrade image staged.",
            "Run onie-install upgrade to next image with {title} configured.",
            "After reboot, new image options visible; existing {title} "
            "behavior preserved; running-config replays without error."),
         _expect("New options available; existing behavior preserved",
                 "Config lost, feature regression, or upgrade rolled back")),
    ],
    "HA": [
        (_scaffold(
            "{title} active on DUT; IXIA traffic running.",
            "Kill the relevant control-plane process while {title} is active "
            "(use platform debug command).",
            "Process restarts; feature recovers; minimal service "
            "interruption (≤ documented bound)."),
         _expect("Process restarts; feature recovers; interruption ≤ documented bound",
                 "No restart, feature stuck, or interruption > bound")),
    ],
    "Long run": [
        (_scaffold(
            "{title} configured; IXIA generating mixed steady traffic profile.",
            "Run {title} under steady traffic for ≥ 24 hours.",
            "No memory leaks (`show platform process memory` flat); "
            "no functional regressions; counters monotonic."),
         _expect("No leaks; no regression; counters monotonic over 24 h",
                 "Memory growth, counter freeze, or functional drift over the run")),
    ],
    "Management": [
        (_scaffold(
            "DUT bare; NETCONF client (e.g. ncclient) authenticated.",
            "Configure {title} entirely via NETCONF using the YANG model.",
            "NETCONF configuration matches CLI behavior; show commands "
            "consistent across both transports; capability advertised."),
         _expect("NETCONF configuration matches CLI behavior",
                 "Schema gap, transport rejects valid config, or CLI/NETCONF view diverge")),
    ],
    "Tech-support": [
        (_scaffold(
            "{title} exercised through Basic Functionality + at least one "
            "Packet validation row; alarms triggered if applicable.",
            "Collect tech-support after exercising {title}.",
            "Tech-support contains: relevant show commands, running-config, "
            "alarm/syslog entries, kernel forwarding tables for the EVI."),
         _expect("Tech-support contains the relevant evidence for {title}",
                 "Missing show output, missing logs, or missing FIB tables")),
    ],
}


# --- RFC content-aware row dispatch ─────────────────────────────────────────
# When a requirement is RFC-sourced we look at title + must_statements
# keywords and emit a row tuned to the *mechanism* (DF election, route
# type N, MAC mobility, label allocation, BUM forwarding, ...).  These
# rows replace the generic Basic Functionality / Packet validation rows
# for the matched mechanism — the generic rows still apply to other
# categories (Feature interaction, Tech-support, ...).
#
# Each entry: (keyword_set_in_title_or_body, category, action, expectation)
# A requirement may match multiple entries; all matching rows are emitted.

RFC_CONTENT_PATTERNS: list[tuple[set[str], str, str, str]] = [
    # ── Route Type 1 (Ethernet A-D per ES / per EVI) ─────────────────────
    ({"ethernet a-d", "auto-discovery route", "type 1", "ad route"},
     "Packet validation",
     _scaffold(
        "Two-PE topology, multi-homed CE, {title} configured.",
        "Trigger Ethernet A-D route generation (advertise per-ES and per-EVI); "
        "capture BGP UPDATE on the wire with tcpdump / wireshark.",
        "Route type 1 NLRI matches RFC7432bis §7.1 encoding (RD + ESI + Eth-Tag); "
        "ESI Label extended community carries the right bits."),
     _expect(
        "Route type 1 encoded per RFC7432bis §7.1; ESI Label EC correct",
        "Encoding deviation, missing ESI Label EC, or wrong split-horizon bit")),

    # ── Route Type 2 (MAC/IP advertisement) ──────────────────────────────
    ({"mac/ip", "mac advertisement", "type 2", "type-2"},
     "Packet validation",
     _scaffold(
        "Two-PE topology, EVPN instance up, host MACs learned on access side.",
        "Send a known unicast frame from IXIA → DUT; capture the BGP MAC/IP "
        "Advertisement route on the PE↔PE link.",
        "Route type 2 carries: RD, ESI, Eth-Tag, MAC, MAC length=48, "
        "(optional IP), MPLS Label1 [+ Label2] per RFC7432bis §7.2."),
     _expect(
        "Route type 2 encoded per RFC7432bis §7.2 with correct labels",
        "MAC length ≠ 48, missing label, or label assignment violates §7.2")),

    # ── Route Type 3 (Inclusive Multicast) ───────────────────────────────
    ({"inclusive multicast", "type 3", "type-3", "im route", "imet"},
     "Packet validation",
     _scaffold(
        "Two-PE EVPN instance with BUM forwarding enabled (ingress replication).",
        "Trigger Inclusive Multicast Ethernet Tag route generation; observe "
        "BGP UPDATEs and PMSI Tunnel attribute encoding.",
        "Route type 3 NLRI per RFC7432bis §7.3; PMSI Tunnel attribute "
        "encodes the tunnel type, label, and tunnel ID correctly."),
     _expect(
        "Route type 3 encoded per RFC7432bis §7.3; PMSI Tunnel attribute correct",
        "Wrong tunnel type, missing PMSI Tunnel attribute, or label mismatch")),

    # ── Route Type 4 (Ethernet Segment) ──────────────────────────────────
    ({"ethernet segment route", "type 4", "type-4", "es route", "es-import"},
     "Packet validation",
     _scaffold(
        "Two-PE topology with multi-homed CE; ES configured on both PEs.",
        "Configure {title}; capture the ES route advertised on PE↔PE link.",
        "Route type 4 carries the right RD + ESI + Originator-IP per "
        "RFC7432bis §7.4; ES-Import RT extended community present."),
     _expect(
        "Route type 4 encoded per RFC7432bis §7.4; ES-Import RT EC present",
        "Missing ES-Import RT, wrong ESI, or DF election fails to converge")),

    # ── Designated Forwarder election ────────────────────────────────────
    ({"designated forwarder", "df election", "df-election",
      "df algorithm", "service carving", "highest-random-weight",
      "highest-preference"},
     "Basic Functionality",
     _scaffold(
        "Two PEs sharing one ES; configure both with the same DF algorithm "
        "({title} algorithm).",
        "Bring up the ES; observe DF election convergence; force a re-election "
        "(remove one PE, add it back).",
        "Exactly one DF elected per ES per VLAN; non-DF blocks BUM on access; "
        "re-election converges within documented bound."),
     _expect(
        "Exactly one DF per ES per VLAN; convergence per RFC7432bis §8 / RFC8584",
        "Two DFs (split-brain), non-DF leaks BUM, or election does not converge")),

    # ── MAC Mobility / Sticky MAC / mass withdrawal ──────────────────────
    ({"mac mobility", "mass withdrawal", "mass-withdrawal",
      "fast convergence", "sticky mac"},
     "Packet validation",
     _scaffold(
        "Two-PE EVPN instance; CE host moves between PEs.",
        "Move a host from PE1 to PE2; capture the MAC Mobility extended "
        "community on the new advertisement.",
        "MAC Mobility extended community carries an incremented sequence "
        "number; old advertisement withdrawn within fast-convergence bound."),
     _expect(
        "MAC Mobility EC sequence increments; withdrawal within bound",
        "Sequence does not increment, no withdrawal, or stale MAC entry remains")),

    # ── ESI types ────────────────────────────────────────────────────────
    ({"esi type", "ethernet segment identifier", "type 0 esi",
      "type 1 esi", "type 4 esi", "type 5 esi"},
     "Basic Functionality",
     _scaffold(
        "Two PEs configured with the ESI type under test.",
        "Configure ESI per {title} (manual/LACP/router-ID/AS-based) on both "
        "PEs of the multi-home group.",
        "Both PEs derive identical ESI; ES route advertised; "
        "DF election converges; access-side LAG comes up."),
     _expect(
        "Identical ESI on both PEs; DF converges; access LAG up",
        "ESI mismatch, ES route not advertised, or LAG never comes up")),

    # ── Label allocation / split horizon ─────────────────────────────────
    ({"label allocation", "split horizon", "split-horizon",
      "esi label", "per-es label"},
     "Packet validation",
     _scaffold(
        "Two-PE EVPN with multi-homed CE; ESI Label allocated.",
        "Send BUM traffic from PE1 → PE2 carrying ESI Label; observe "
        "PE2's split-horizon enforcement on the shared ES.",
        "PE2 drops frames whose ESI Label matches its own ES; non-shared-ES "
        "frames forwarded normally."),
     _expect(
        "Split horizon drops shared-ES BUM; non-shared forwarded",
        "BUM looped on the shared ES, or non-shared BUM dropped")),

    # ── BUM forwarding (ingress replication / P2MP) ──────────────────────
    ({"bum", "broadcast unknown multicast", "ingress replication",
      "p2mp", "imet route"},
     "Packet validation",
     _scaffold(
        "Multi-PE EVPN with ingress replication; BUM source on access side.",
        "Send broadcast / unknown-unicast / multicast frames from a CE; "
        "trace replication on the PE↔PE links.",
        "Each remote PE receives exactly one copy per IMET route; "
        "no duplicate replication; receiver counters match expectation."),
     _expect(
        "BUM replicated once per remote PE; no duplication",
        "Duplicate replication, missing replication, or wrong PE receives BUM")),

    # ── Aliasing / backup-path ───────────────────────────────────────────
    ({"aliasing", "backup path", "backup-path"},
     "Packet validation",
     _scaffold(
        "Multi-homed CE on two PEs (PE1 active DF, PE2 non-DF); known unicast "
        "to a MAC behind both PEs.",
        "Send known-unicast traffic toward the multi-homed MAC; observe "
        "load-share / backup-path behavior on PE↔PE.",
        "Traffic load-shared per the documented mode (all-active) or "
        "single-path on DF (single-active); on DF flap, backup path takes over "
        "within fast-convergence bound."),
     _expect(
        "Load-share or backup-path per spec; failover within bound",
        "Black-hole during failover, no load-share, or wrong PE receives traffic")),

    # ── BGP capability / negotiation ─────────────────────────────────────
    ({"capability", "open message", "negotiat"},
     "3rd Party Interoperability",
     _scaffold(
        "Exaware DUT + 3rd-party speaker; BGP EVPN session about to come up.",
        "Bring up the BGP session; capture OPEN messages on both sides.",
        "Both sides advertise the L2VPN-EVPN AFI/SAFI capability; "
        "session reaches Established; route exchange begins."),
     _expect(
        "L2VPN-EVPN AFI/SAFI capability advertised; session up",
        "Missing capability, NOTIFICATION on OPEN, or session never reaches Established")),
]


def rfc_actions_for(title: str, body: str, category: str
                    ) -> list[tuple[str, str]]:
    """Return RFC-specific (action, expectation) pairs for `category` whose
    keyword set matches `title`/`body`. Empty list = use generic templates.
    """
    blob = f"{title}\n{body}".lower()
    out: list[tuple[str, str]] = []
    for keywords, cat, action, expectation in RFC_CONTENT_PATTERNS:
        if cat != category:
            continue
        if any(kw in blob for kw in keywords):
            out.append((action, expectation))
    return out


def categories_for_tags(tags: list[str], source: str = "spec") -> list[str]:
    """Union of categories for the given domain tags, plus ALWAYS_CATEGORIES.

    `source="rfc"` masks out CLI/Management/Upgrade — those describe vendor
    platform behavior, not the protocol behavior an RFC defines.
    """
    out: list[str] = []
    seen: set[str] = set()
    for cat in ALL_CATEGORIES:  # iterate in template order
        if source == "rfc" and cat in RFC_EXCLUDED_CATEGORIES:
            continue
        applies = cat in ALWAYS_CATEGORIES
        if not applies:
            for tag in tags:
                if cat in TAG_TO_CATEGORIES.get(tag, []):
                    applies = True
                    break
        if applies and cat not in seen:
            out.append(cat)
            seen.add(cat)
    return out
