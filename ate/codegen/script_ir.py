"""Executable test-script IR — the typed layer between a flow and Java code.

M1 stops at prose: `Flow.setup/action/verify` are English blobs, and
`AtomicRow` is six strings. Nothing in that model says *which port*, *which
counter*, *what value*, *how long to wait* — so nothing in it can be compiled.

`TestScript` is the missing layer. A `Step` is one typed, executable unit that
an emitter can turn into a line of Java (or, later, Python). Steps carry their
own stable ID and requirement provenance, so traceability survives all the way
into the generated source: a reviewer reading `TC02_...java` can still get back
to `EVPNS-REQ#70` and `RFC7432bis-§7.2`.

Deliberately small. Nine kinds cover the whole Eyal/Exaware M2 sequence
(3 ACs on one DUT, MAC learning, Type-2/Type-3 advertisement, MAC move,
aging). Anything a kind cannot express becomes `Step.todo`, which the emitter
renders as a compiling `// TODO` stub rather than an invented assertion — the
same de-invention posture `cli_crosscheck.py` applies to the test plan.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class StepKind(str, Enum):
    """What a step *does*. One emitter branch per kind."""

    #: Apply CLI on the DUT and validate the commit.
    CONFIG = "config"
    #: Enable / disable a single named IXIA traffic item.
    TRAFFIC_STATE = "traffic_state"
    #: Start / stop the IXIA traffic engine as a whole.
    TRAFFIC_START = "traffic_start"
    TRAFFIC_STOP = "traffic_stop"
    #: Sleep a fixed number of seconds (MAC aging, convergence).
    WAIT = "wait"
    #: Run a `show` and assert expected lines (regex), polling to a timeout.
    VERIFY_CLI = "verify_cli"
    #: Assert IXIA per-port / per-flow statistics.
    VERIFY_IXIA = "verify_ixia"
    #: Assert a BGP EVPN route is present / withdrawn.
    VERIFY_ROUTE = "verify_route"
    #: Negative assertion — snapshot, act, assert nothing changed.
    VERIFY_NO_EVENT = "verify_no_event"


class Step(BaseModel):
    """One executable step.

    `id` is stable (`FLOW-030.S07`) exactly like flow IDs are stable: a
    reviewer cites it, the dirty queue keys on it, and regeneration must not
    renumber it.
    """

    id: str
    kind: StepKind
    #: Human sentence. Becomes the CompassReporter level title, so it is what a
    #: QA engineer reads in the run report. Keep it one line.
    text: str

    # ── CONFIG / VERIFY_CLI ──────────────────────────────────────────────
    #: Key into the generated `EvpnCommands` enum, e.g.
    #: "CONFIGURE_L2_SERVICES_EVPN_$". Never a raw CLI string: routing every
    #: command through the enum is what keeps generated code grounded in the
    #: CLI doc.
    command: str = ""
    #: Positional arguments substituted into the command's `%s` slots.
    args: list[str] = Field(default_factory=list)
    #: Name of the `EvpnParams` constant holding the expected-line array.
    expect_key: str = ""

    # ── traffic ──────────────────────────────────────────────────────────
    traffic_items: list[str] = Field(default_factory=list)
    #: For TRAFFIC_STATE: True → unsuspend, False → suspend.
    enabled: bool | None = None

    # ── wait ─────────────────────────────────────────────────────────────
    seconds: int = 0

    # ── provenance ───────────────────────────────────────────────────────
    #: SFS / RFC requirement IDs this step exercises. Rendered as a Javadoc
    #: comment above the step so the generated file is self-documenting.
    req_ids: list[str] = Field(default_factory=list)
    #: Set when the step cannot be fully expressed from the documents alone —
    #: typically an expected value that needs real device output. The emitter
    #: renders a compiling TODO instead of guessing.
    todo: str = ""

    @property
    def needs_lab_data(self) -> bool:
        return bool(self.todo)


class TestScript(BaseModel):
    """One generated JSystem test class."""

    flow_id: str                 # "FLOW-030"
    class_name: str              # "TC02_EvpnType2MacIpAdvertisement"
    method_name: str             # "evpnType2MacIpAdvertisement"
    title: str
    summary: str
    steps: list[Step] = Field(default_factory=list)
    #: Flow IDs whose service state this script assumes (FLOW-010 is the
    #: prerequisite for FLOW-030 / FLOW-031 per the Exaware M2 scoping).
    depends_on: list[str] = Field(default_factory=list)

    @property
    def covered_req_ids(self) -> list[str]:
        seen: list[str] = []
        for s in self.steps:
            for r in s.req_ids:
                if r not in seen:
                    seen.append(r)
        return seen

    @property
    def open_todos(self) -> list[Step]:
        return [s for s in self.steps if s.needs_lab_data]
