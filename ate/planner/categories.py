"""Test plan categories and per-(tag, category) action templates.

Two pieces of logic live here:

1. **Applicability matrix** (TAG_TO_CATEGORIES): which Categories are relevant
   for a requirement given its domain tags. We don't apply every Category to
   every requirement — that's how v1 produced 960 rows of generic boilerplate.

2. **Action templates** (CATEGORY_ACTIONS): per-Category action steps + expectations.
   Templates use {title}, {req_id}, {must}, {rfc_refs}, {first_cli_line}.

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

# Per-Category: list of (action_template, expectation_template) pairs.
# Templates may use the placeholders:
#   {title}, {req_id}, {section}, {must_short}, {rfc_refs}, {cli_hint}
# Multiple pairs per Category produce multiple rows per applicable requirement.
CATEGORY_ACTIONS: dict[str, list[tuple[str, str]]] = {
    "CLI configuration": [
        ("Configure {title} {section}{cli_hint}; save and reload",
         "Configuration accepted, persists across reload, visible in `show running-config`"),
        ("Edit one parameter of the configuration; commit",
         "Edit applied; `show running-config` reflects the change"),
        ("Delete the configuration; commit",
         "Configuration removed; related show commands report empty/default"),
        ("Apply factory-default; replay the configuration",
         "After replay the configuration is identical (use `diff` on saved configs)"),
        ("Run rollback after a configuration change",
         "Previous configuration restored without service disruption"),
    ],
    "Basic Functionality": [
        ("Verify happy-path operation of {title}{rfc_hint}",
         "Feature behaves per requirement{must_hint}"),
        ("Verify default behavior when configuration is omitted",
         "System falls back to documented default; no spurious alarms"),
    ],
    "On The Fly changes": [
        ("Modify the {title} configuration while traffic flows",
         "Modification applied without service interruption{must_hint}"),
    ],
    "Packet validation": [
        ("Send valid traffic exercising {title}",
         "Traffic forwarded as expected; counters increment{must_hint}"),
    ],
    "Malformed/unsupported packets": [
        ("Inject malformed/unsupported variants of {title} traffic",
         "Variants dropped; no crash; error counter increments; "
         "syslog records the event"),
    ],
    "Feature interaction": [
        ("Combine {title} with {neighbor_feature}",
         "Both features operate per spec; no regression{must_hint}"),
    ],
    "3rd Party Interoperability": [
        ("Interop {title} with a 3rd-party PE/CE per {rfc_refs_or_rfc7432bis}",
         "Interop succeeds; routes/frames exchanged correctly"),
    ],
    "Scale": [
        ("Scale {title} to documented system limit",
         "Limit reached; performance and stability remain within bounds"),
    ],
    "Performance": [
        ("Measure {title} throughput / latency / convergence under documented load",
         "All metrics within the bounds defined by the spec/SLA"),
    ],
    "Robustness": [
        ("Reset the Exaware while {title} is active",
         "Feature recovers automatically after reset; no data loss"),
        ("Power-cycle the Exaware while {title} is active",
         "Feature recovers after power-cycle; configuration intact"),
        ("Flap the relevant interface while {title} is active",
         "Feature recovers; convergence within fast-convergence bounds"),
    ],
    "PM": [
        ("Verify PM counters relevant to {title}",
         "Counters increment correctly; clear works; values persist across reload"),
    ],
    "Alarms/Logs/Syslog": [
        ("Trigger an error condition for {title} (misconfig / link failure / peer down)",
         "Alarm raised; syslog entry generated; alarm clears when condition is resolved"),
    ],
    "Upgrade": [
        ("Run onie-install upgrade with {title} configured",
         "New configuration options available; existing behavior preserved"),
    ],
    "HA": [
        ("Kill the relevant process while {title} is active",
         "Process restarts; feature recovers; minimal service interruption"),
    ],
    "Long run": [
        ("Run {title} under steady traffic for ≥ 24 hours",
         "No memory leaks; no functional regressions; counters monotonic"),
    ],
    "Management": [
        ("Configure {title} via NETCONF",
         "NETCONF configuration matches CLI behavior; show commands consistent"),
    ],
    "Tech-support": [
        ("Collect tech-support after exercising {title}",
         "Tech-support contains relevant show commands, configs, and logs"),
    ],
}


def categories_for_tags(tags: list[str]) -> list[str]:
    """Union of categories for the given domain tags, plus ALWAYS_CATEGORIES."""
    out: list[str] = []
    seen: set[str] = set()
    for cat in ALL_CATEGORIES:  # iterate in template order
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
