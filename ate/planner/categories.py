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

import re

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
            "System falls back to documented default; zero alarms raised "
            "during the no-config window; no crash (uptime continuous)."),
         _expect("System falls back to documented default; zero unexpected alarms",
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
            "Two-PE topology with {title} configured to the documented system "
            "limit (64K MACs / 32 EVIs / 16 ESs — adjust per platform spec; "
            "check `show evpn summary` for the live ceiling).",
            "Scale {title} to the documented maximum at 1K entries/s; hold "
            "for ≥ 5 minutes; sample CPU and memory every 60 s.",
            "Limit reached without crash; CPU 5-min avg ≤ 70%; memory growth "
            "over the run ≤ 5%; incremental convergence ≤ 2× idle baseline."),
         _expect("Limit reached; CPU ≤ 70%; memory growth ≤ 5%; convergence ≤ 2× baseline",
                 "Crash, OOM, CPU > 70%, memory > 5% growth, or per-route convergence > 2× baseline")),
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
            "Feature recovers automatically within ≤ 30 s; data-path remains "
            "forwarding (IXIA loss histogram shows ≤ 1 s of zero-bps)."),
         _expect("Feature recovers ≤ 30 s; data-path interruption ≤ 1 s",
                 "Full outage > 1 s, recovery > 30 s, no auto-recovery, or feature stuck after recovery")),
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
            "Feature recovers; convergence ≤ 1 s "
            "(per [RFC7432bis] §8 mass-withdrawal fast-convergence target)."),
         _expect("Feature recovers; convergence ≤ 1 s per RFC 7432bis §8",
                 "Convergence > 1 s or stale FIB after flap")),
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
            "Process restarts within ≤ 5 s; feature recovers within ≤ 30 s; "
            "service interruption ≤ 1 s on the access port."),
         _expect("Process restarts ≤ 5 s; feature recovers ≤ 30 s; interruption ≤ 1 s",
                 "No restart, restart > 5 s, recovery > 30 s, feature stuck, or interruption > 1 s")),
    ],
    "Long run": [
        (_scaffold(
            "{title} configured; IXIA generating mixed steady traffic profile.",
            "Run {title} under steady traffic for ≥ 24 hours.",
            "Memory growth over the 24 h run ≤ 5% of hour-0 baseline; "
            "no functional regressions; counters monotonic; zero alarms "
            "outside test-induced events."),
         _expect("Memory growth ≤ 5% over 24 h; no regression; counters monotonic; zero unexpected alarms",
                 "Memory growth > 5%, counter freeze, functional drift, or any unexpected alarm")),
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
        "re-election converges within ≤ 3 s of the trigger event."),
     _expect(
        "Exactly one DF per ES per VLAN; convergence ≤ 3 s per RFC 7432bis §8 / RFC 8584",
        "Two DFs (split-brain), non-DF leaks BUM, or election convergence > 3 s")),

    # ── MAC Mobility / Sticky MAC / mass withdrawal ──────────────────────
    ({"mac mobility", "mass withdrawal", "mass-withdrawal",
      "fast convergence", "sticky mac"},
     "Packet validation",
     _scaffold(
        "Two-PE EVPN instance; CE host moves between PEs.",
        "Move a host from PE1 to PE2; capture the MAC Mobility extended "
        "community on the new advertisement.",
        "MAC Mobility extended community carries an incremented sequence "
        "number; old advertisement withdrawn within ≤ 1 s (RFC 7432bis §8 "
        "fast-convergence target)."),
     _expect(
        "MAC Mobility EC sequence increments; withdrawal within ≤ 1 s",
        "Sequence does not increment, no withdrawal, withdrawal > 1 s, or stale MAC entry remains")),

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
        "within ≤ 1 s (RFC 7432bis §8 fast-convergence target)."),
     _expect(
        "Load-share or backup-path per spec; failover within ≤ 1 s",
        "Black-hole during failover, no load-share, failover > 1 s, or wrong PE receives traffic")),

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


# ─── Flow × Category overlays ───────────────────────────────────────────
# Flows give the *what* (which use case); category overlays give the
# *how* (which test technique). For each flow row we render the flow's
# Setup/Action/Verify base, then the category-specific overlay sharpens
# the action and verify, and supplies a category-specific Pass/Fail-on.
#
# Output is **numbered** Setup/Action/Verify steps so the row maps
# 1-to-1 onto codegen-friendly procedure: each step becomes one runner
# call. Closes the QA pushback that prose-form rows are too template-
# shaped for the automation-codegen PoC.

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Za-z`])")


def _split_steps(prose: str) -> list[str]:
    """Split a prose block into sentence-shaped steps.

    The flow catalog stores each section as one or two sentences for
    readability; this helper turns that into numbered steps for codegen.
    Empty inputs yield a single placeholder step so the structure is
    preserved.
    """
    text = (prose or "").strip()
    if not text:
        return ["(no steps documented)"]
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    return parts or [text]


def _numbered_block(label: str, items: list[str]) -> str:
    if len(items) == 1:
        return f"{label}:\n  1. {items[0]}"
    return f"{label}:\n" + "\n".join(
        f"  {i}. {s}" for i, s in enumerate(items, 1)
    )


def _scaffolded(setup: list[str] | str, action: list[str] | str,
                verify: list[str] | str) -> str:
    """Render Setup/Action/Verify with numbered sub-steps. Accepts either
    a list (preferred — each item is one numbered step) or a prose
    string (split on sentence boundaries).
    """
    s = setup if isinstance(setup, list) else _split_steps(setup)
    a = action if isinstance(action, list) else _split_steps(action)
    v = verify if isinstance(verify, list) else _split_steps(verify)
    return "\n".join([
        _numbered_block("Setup", s),
        _numbered_block("Action", a),
        _numbered_block("Verify", v),
    ])


def _expected(pass_: str, fail_on: str) -> str:
    return f"Pass:    {pass_}\nFail-on: {fail_on}"


# Map flow-id prefix → canonical "show" verification commands. Keeps
# verify steps from drifting into prose; codegen can mechanically
# capture each named command's output.
_FLOW_SHOW_CMDS: dict[str, list[str]] = {
    "FLOW-01": [  # EVPN service-type bring-up family
        "show evpn evi", "show evpn mac address-table",
        "show running-config | include evpn",
    ],
    "FLOW-02": [  # multi-homing + DF
        "show evpn ethernet-segment",
        "show evpn ethernet-segment detail",
        "show evpn df", "show running-config | include ethernet-segment",
    ],
    "FLOW-03": [  # route-type packet validation
        "show bgp l2vpn evpn", "show bgp l2vpn evpn detail",
        "show evpn mac address-table",
    ],
    "FLOW-04": [  # MAC mobility
        "show evpn mac address-table",
        "show bgp l2vpn evpn", "show evpn duplicate-mac",
    ],
    "FLOW-05": [  # Static MAC
        "show evpn mac address-table",
        "show running-config | include mac-address-static",
    ],
    "FLOW-06": [  # split-horizon / aliasing
        "show evpn ethernet-segment", "show bgp l2vpn evpn",
        "show evpn mac address-table",
    ],
    "FLOW-07": [  # interop
        "show bgp neighbor", "show bgp l2vpn evpn",
    ],
    "FLOW-08": [  # scale
        "show platform process memory", "show evpn summary",
        "show evpn mac address-table count",
    ],
    "FLOW-09": [  # robustness / upgrade / netconf
        "show alarms", "show platform process",
        "show running-config", "show version",
    ],
    "FLOW-10": [  # alarms / syslog
        "show alarms", "show log",
    ],
    "FLOW-11": [  # on-the-fly
        "show running-config", "show evpn evi",
    ],
    "FLOW-12": [  # long run
        "show platform process memory",
        "show evpn mac address-table count", "show alarms",
    ],
    "FLOW-13": [  # EVI-to-EVI MPLS transport / tunnel interconnect (RFC 4364)
        "show mpls forwarding-table", "show mpls lsp",
        "show bgp l2vpn evpn", "show route table inet.3",
        "show evpn evi",
    ],
}


def _show_cmds_for(flow) -> list[str]:
    for prefix, cmds in _FLOW_SHOW_CMDS.items():
        if flow.id.startswith(prefix):
            return cmds
    return ["show running-config", "show evpn evi"]


def _rfc_phrase(flow) -> str:
    return ", ".join(flow.rfc_refs) if flow.rfc_refs else "(no RFC refs)"


def overlay_for_category(flow, category: str) -> tuple[str, str]:
    """Return (action_steps, expectation) for `flow` viewed through
    the lens of `category`. Each return is rendered as numbered
    Setup/Action/Verify steps so codegen can iterate. Verify steps
    name concrete `show` commands wherever possible.
    """
    setup_steps = _split_steps(flow.setup)
    action_steps = _split_steps(flow.action)
    verify_steps = _split_steps(flow.verify)
    show_cmds = _show_cmds_for(flow)
    rfc = _rfc_phrase(flow)

    if category == "Basic Functionality":
        verify = verify_steps + [
            f"Capture and snapshot: {', '.join(f'`{c}`' for c in show_cmds[:3])}.",
        ]
        return (
            _scaffolded(setup_steps, action_steps, verify),
            _expected(flow.pass_, flow.fail_on),
        )

    if category == "Packet validation":
        action = action_steps + [
            "Capture BGP UPDATEs on the PE↔PE link and access-side frames "
            "on ingress / egress ACs (tcpdump / wireshark or IXIA capture).",
            f"Decode each captured packet and compare every NLRI / extended-"
            f"community / label field against {rfc}.",
        ]
        verify = verify_steps + [
            f"Snapshot `{show_cmds[0]}` and `show bgp l2vpn evpn` before "
            "and after the action — diff against the documented expected "
            "delta.",
            f"Cross-check encoded fields against {rfc} byte for byte.",
        ]
        return (
            _scaffolded(setup_steps, action, verify),
            _expected(
                f"{flow.pass_} Encoded fields match {rfc} byte for byte.",
                f"{flow.fail_on} OR any encoded field deviates from {rfc}.",
            ),
        )

    if category == "Malformed/unsupported packets":
        return (
            _scaffolded(
                setup_steps + ["IXIA primed with a fault-injection script."],
                [
                    "Inject a malformed variant of the flow's protocol "
                    "traffic (bad TLV length).",
                    "Inject a variant with reserved bits set on the NLRI.",
                    "Inject an oversized field (e.g. RD > 8 octets).",
                    "Inject a truncated NLRI / shortened length-prefix.",
                ],
                [
                    "Each malformed variant is dropped at ingress; the DUT "
                    "does not crash or restart.",
                    "Per-variant error counter increments by exactly one in "
                    "the relevant `show` (e.g. `show bgp neighbor errors`).",
                    "Syslog records each event with a structured reason "
                    "(visible via `show log | include malformed`).",
                ],
            ),
            _expected(
                "Each variant dropped; no crash; error counter +1; syslog "
                "entry present per event.",
                "Crash, stale state, missing syslog, or malformed packet "
                "propagated to peer.",
            ),
        )

    if category == "On The Fly changes":
        return (
            _scaffolded(
                setup_steps + [
                    "IXIA traffic flowing through the flow's data path for "
                    "≥ 1 minute.",
                ],
                action_steps + [
                    "While traffic continues, revert each modified parameter "
                    "to its original value and commit.",
                ],
                [
                    "IXIA reports zero (or near-zero) loss during the change "
                    "window — capture per-second loss histogram.",
                    f"`{show_cmds[0]}` reflects the new value within ≤ 1 s.",
                    "Running-config diff (before vs. after) shows only the "
                    "intended change; no incidental drift.",
                    "After revert, IXIA loss returns to baseline; running-"
                    "config matches the original byte for byte.",
                ],
            ),
            _expected(
                "Modification applied without service interruption; "
                "running-config consistent; revert clean.",
                "Traffic loss > 0 packets on a documented hitless change, "
                "new config not active within 1 s, or revert leaves drift.",
            ),
        )

    if category == "Feature interaction":
        return (
            _scaffolded(
                setup_steps + [
                    "A neighbor feature (BGP convergence, MPLS encap, QoS, "
                    "or another EVPN service) configured alongside on the "
                    "same DUT.",
                ],
                [
                    "Bring up the neighbor feature first; verify its "
                    "baseline `show` output.",
                    f"Bring up the flow on top: {flow.action}",
                    "Drive traffic through both features simultaneously "
                    "for ≥ 1 minute.",
                ],
                [
                    f"`{show_cmds[0]}` reports the flow operating per spec.",
                    "Neighbor feature's `show` output unchanged from baseline.",
                    "No new alarm raised by either feature.",
                ],
            ),
            _expected(
                "Both features operate per spec; no regression in either's "
                "show output or counters.",
                "Either feature breaks, counters stop, or one masks the other.",
            ),
        )

    if category == "3rd Party Interoperability":
        return (
            _scaffolded(
                [
                    "Exaware DUT + 3rd-party PE (Cisco/Juniper) connected "
                    "over MPLS.",
                    "BGP EVPN session up between the two; both sides "
                    "advertise the L2VPN-EVPN AFI/SAFI capability.",
                ] + setup_steps,
                [
                    f"Configure the flow on the DUT: {flow.action}",
                    "Configure the symmetric flow on the 3rd-party side "
                    "using its native CLI.",
                    "Drive bidirectional traffic between the two PEs.",
                ],
                [
                    "`show bgp l2vpn evpn` on each side lists the routes "
                    "advertised by the peer.",
                    f"Routes installed in FIB; data plane forwards "
                    f"bidirectionally per {rfc}.",
                    "Route encoding accepted by both sides — no NOTIFICATION "
                    "and no rejected NLRI.",
                ],
            ),
            _expected(
                "Interop succeeds; routes/frames exchanged correctly.",
                "Route rejected, NOTIFICATION on OPEN, encoding mismatch, "
                "or one-way black-hole.",
            ),
        )

    if category == "Scale":
        return (
            _scaffolded(
                [
                    "Two-PE topology with the flow's service configured.",
                    "IXIA scale rig connected on access; documented "
                    "ceiling: 64K MACs / 32 EVIs / 16 multi-homed ESs "
                    "(adjust per platform spec).",
                ],
                [
                    "Use IXIA to advertise / install entries up to the "
                    "documented system limit at 1K entries/s.",
                    "Hold for ≥ 5 minutes at the ceiling; sample CPU "
                    "(`show platform process cpu`) and memory "
                    "(`show platform process memory`) every 60 s.",
                    "Trigger an incremental change while at scale "
                    "(advertise one more entry, then withdraw); "
                    "measure first-packet-after-advertise on IXIA.",
                ],
                [
                    f"`{show_cmds[0]}` reaches the documented limit without "
                    "rejection.",
                    "CPU 5-min average ≤ 70%; memory growth over the run "
                    "≤ 5% of baseline.",
                    "Incremental convergence ≤ 2× the idle baseline "
                    "(< 500 ms typical).",
                ],
            ),
            _expected(
                "Limit reached; CPU ≤ 70% (5-min avg); memory growth "
                "≤ 5%; incremental convergence ≤ 2× baseline.",
                "Crash, OOM, rejected entries below ceiling, CPU > 70% "
                "sustained, memory growth > 5%, or convergence > 2× "
                "baseline.",
            ),
        )

    if category == "Performance":
        return (
            _scaffolded(
                [
                    "Two-PE topology with the flow configured.",
                    "IXIA scale rig generating documented load profile.",
                ],
                [
                    "Measure throughput on the data path under documented "
                    "load.",
                    "Measure end-to-end latency (per-frame median + 99th "
                    "percentile).",
                    "Measure convergence on a documented event (e.g. ES flap, "
                    "MAC withdrawal).",
                ],
                [
                    "Throughput ≥ 99% of offered line rate (e.g. ≥ 0.99 "
                    "Gbps on a 1 Gbps port) under the documented load.",
                    "Latency p99 ≤ 100 µs end-to-end across the data path.",
                    "Convergence on documented events: MAC withdrawal "
                    "≤ 1 s; ES flap ≤ 1 s; numeric values recorded for "
                    "each metric against the listed thresholds.",
                ],
            ),
            _expected(
                "Throughput ≥ 99% line rate; latency p99 ≤ 100 µs; "
                "convergence ≤ 1 s on documented events.",
                "Throughput < 99% line rate, latency p99 > 100 µs, or "
                "convergence > 1 s on any documented event.",
            ),
        )

    if category == "Robustness":
        return (
            _scaffolded(
                setup_steps + [
                    "IXIA generating background traffic on the flow's data "
                    "path."
                ],
                [
                    "Identify the relevant control-plane process via "
                    "`show platform process | include evpn` (or `bgp`).",
                    "Reset that process using the documented platform "
                    "reset / debug CLI.",
                    "Watch IXIA loss histogram during the reset.",
                ],
                [
                    "Process restarts within ≤ 5 s of the kill signal.",
                    "Data-path keeps forwarding — IXIA loss histogram "
                    "records ≤ 1 s of zero-bps on the access port.",
                    f"`{show_cmds[0]}` recovers to its pre-reset state "
                    "within ≤ 30 s.",
                ],
            ),
            _expected(
                "Process restarts ≤ 5 s; data-path outage ≤ 1 s; "
                "feature recovers ≤ 30 s.",
                "Full outage > 1 s, restart > 5 s, no auto-recovery, "
                "or feature stuck after recovery.",
            ),
        )

    if category == "PM":
        return (
            _scaffolded(
                setup_steps + ["Reference traffic load applied for ≥ 1 min."],
                [
                    f"Snapshot counters: {', '.join(f'`{c}`' for c in show_cmds[:2])}.",
                    "Issue `clear counters` (or the documented per-feature "
                    "clear command).",
                    "Resume traffic; re-read counters after another ≥ 1 min.",
                    "Reload the DUT; re-read counters after boot.",
                ],
                [
                    "Counters increment monotonically while traffic flows.",
                    "Clear command resets the counters to zero (or to the "
                    "documented baseline).",
                    "After reload, counter persistence matches the documented "
                    "behaviour for each counter.",
                ],
            ),
            _expected(
                "Counters increment correctly; clear works; persistence per spec.",
                "Counter freeze, clear no-op, or persistence broken.",
            ),
        )

    if category == "Alarms/Logs/Syslog":
        return (
            _scaffolded(
                setup_steps + [
                    "Syslog destination configured (collector reachable).",
                    "Each documented alarm condition primed (mac-limit, "
                    "peer flap, mismatched DF algorithm, etc.).",
                ],
                [
                    "Trigger each documented error condition in sequence.",
                    "After each trigger, run `show alarms` and inspect the "
                    "syslog feed at the collector.",
                    "Resolve each condition and re-check.",
                ],
                [
                    "Each event raises an alarm at the documented severity.",
                    "Each event produces a structured syslog entry with the "
                    "documented fields (timestamp, severity, facility, "
                    "feature, reason).",
                    "Each alarm clears within ≤ 30 s of the resolution "
                    "event (verifiable via `show alarms` polling).",
                ],
            ),
            _expected(
                "Per event: correct severity + syslog entry; alarm clears "
                "within ≤ 30 s of resolution.",
                "No alarm, wrong severity, missing syslog, or alarm still "
                "active > 30 s after resolution.",
            ),
        )

    if category == "Upgrade":
        return (
            _scaffolded(
                [
                    "DUT with the flow configured on the current image.",
                    "Upgrade image staged on the ONIE image server.",
                ],
                [
                    "Save running-config; reload to confirm the baseline "
                    "replays cleanly.",
                    "Run `onie-install` to the next image; reload onto the "
                    "new image.",
                    "Reload again on the new image to confirm idempotence.",
                ],
                [
                    "After upgrade, `show version` reports the new image.",
                    "`show running-config` replays without error; flow comes "
                    "up automatically.",
                    "BGP EVPN session re-establishes; data plane resumes "
                    "forwarding.",
                ],
            ),
            _expected(
                "New image available; flow behaviour preserved across upgrade.",
                "Config lost, feature regression, or upgrade rolled back.",
            ),
        )

    if category == "HA":
        return (
            _scaffolded(
                setup_steps + [
                    "IXIA traffic running on the flow's data path."
                ],
                [
                    "Identify the relevant control-plane process via "
                    "`show platform process`.",
                    "Kill the process via the documented platform debug "
                    "command (not graceful restart).",
                    "Wait for supervisor-initiated restart.",
                ],
                [
                    "Process restarts within ≤ 5 s; `show platform process` "
                    "shows it running again with a new PID.",
                    f"Flow recovers within ≤ 30 s — `{show_cmds[0]}` "
                    "returns to its pre-kill state.",
                    "Service interruption ≤ 1 s on the access port "
                    "(verified via IXIA loss histogram).",
                ],
            ),
            _expected(
                "Process restarts ≤ 5 s; flow recovers ≤ 30 s; data-path "
                "interruption ≤ 1 s.",
                "No restart, restart > 5 s, recovery > 30 s, flow stuck, "
                "or interruption > 1 s.",
            ),
        )

    if category == "Long run":
        return (
            _scaffolded(
                setup_steps + [
                    "IXIA generating mixed steady traffic profile.",
                    "Memory baseline recorded via `show platform process "
                    "memory`.",
                ],
                [
                    "Hold the run for ≥ 24 hours.",
                    "Sample memory hourly: `show platform process memory`.",
                    "Sample alarm log hourly: `show alarms` and `show log "
                    "| include error`.",
                ],
                [
                    "Memory growth over the 24 h run ≤ 5% of the hour-0 "
                    "baseline (no monotonic growth).",
                    "No functional regression — flow still operates per "
                    "Basic Functionality criteria at hour 24.",
                    "Counters monotonic; zero alarms outside the test-"
                    "induced events.",
                ],
            ),
            _expected(
                "Memory growth ≤ 5% over 24 h; no regression; counters "
                "monotonic; zero unexpected alarms.",
                "Memory growth > 5%, counter freeze, functional drift, "
                "or any unexpected alarm during the run.",
            ),
        )

    if category == "Management":
        return (
            _scaffolded(
                [
                    "DUT bare; NETCONF client (e.g. ncclient) authenticated.",
                    "YANG model files for the flow's feature available.",
                ],
                [
                    "Push the flow's canonical configuration via NETCONF "
                    "`<edit-config>`.",
                    "Issue NETCONF `<get-config>` and capture the running "
                    "datastore.",
                    "Issue equivalent CLI `show running-config` and compare.",
                ],
                [
                    "NETCONF capability for the EVPN YANG model advertised "
                    "in the hello.",
                    "`<edit-config>` accepted; running-config matches the "
                    "submitted model.",
                    "CLI and NETCONF views show the same configuration; "
                    "no schema gap.",
                ],
            ),
            _expected(
                "NETCONF configuration matches CLI behaviour.",
                "Schema gap, transport rejects valid config, or "
                "CLI/NETCONF view diverge.",
            ),
        )

    if category == "Tech-support":
        return (
            _scaffolded(
                setup_steps + [
                    "The flow exercised through Basic Functionality and at "
                    "least one Packet validation row.",
                    "Alarms triggered if the flow has any.",
                ],
                [
                    "Run `tech-support` (or the documented bundle command).",
                    "Save the bundle off-box.",
                    "Open the bundle and inspect for the flow's expected "
                    "evidence.",
                ],
                [
                    f"Bundle contains: {', '.join(f'`{c}`' for c in show_cmds[:3])} output.",
                    "Bundle contains running-config and any alarm/syslog "
                    "entries from the run.",
                    "Bundle contains kernel forwarding tables for the EVI "
                    "/ ES / MAC table touched by the flow.",
                ],
            ),
            _expected(
                "Tech-support contains the relevant evidence for the flow.",
                "Missing show output, missing logs, or missing FIB tables.",
            ),
        )

    # Fallback: emit the canonical numbered scaffold.
    return (
        _scaffolded(setup_steps, action_steps, verify_steps),
        _expected(flow.pass_, flow.fail_on),
    )
