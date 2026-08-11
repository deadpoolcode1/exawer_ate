# Lab validation on SUT pc-3021 — 2026-08-11

Exaware reserved SUT **pc-3021** (Yuval Hoffman, 2026-08-10) so the M2 suites
could be validated against real hardware. This records what was found.

Validating on hardware is **above** the M2 bar — the SOW asks for
"integration-ready" test plans, not executed ones — but it is what turns
guessed expectation tables into real ones, so it was worth doing.

## The testbed

`pc-3021` is a JSystem SUT definition,
`cmp-tests-project/src/main/resources/sut/pc3021.xml`.

| Role | Value |
|---|---|
| DUT `CMP1` | `exa-il01-ec-3021` — mgmt **10.3.21.1**, `admin`/`admin` |
| Platform | `Type=edgeCore`, lc0 `lcType=EC300Gig` |
| IXIA app server | **10.1.70.200** (`tate.cmpsys.com`), IxOS 6.30.701.16 |
| IXIA chassis | **10.1.70.108** |
| IXIA vports | pool `data1`: vport1/2/3 = card 5, ports 6/7/8 |
| VLAN | 3321 |

All four hosts respond to ping with SSH open. **The IXIA came with the
reservation** — the mail named only the SUT, so this was confirmed rather than
assumed. Three vports is exactly the AC1/AC2/AC3 the suites model.

## Blocker: the DUT's software has no EVPN

DUT runs **`8.7.0: LAB 904`** (Data Model version 7, ConfD 5.0.7.5, built
080926_2159). EVPN is absent from the data model entirely. Five independent
probes:

| Probe | Result |
|---|---|
| `show evpn global` | `syntax error: element does not exist` |
| `show evpn mac address-table` | `syntax error: element does not exist` |
| `show evpn bum routing-table` | `syntax error: element does not exist` |
| `show ?` | `vpls`, `vpws`, `xconnect` — **no `evpn`** |
| `show bgp table l2vpn ?` | `vpls` only |
| `config: l2-services ?` | `pw-profile`, `vpls`, `vpws`, `xconnect` — no `evpn` |
| `config: routing bgp 100 ?` | no address-family node at all, no `af-l2vpn` |

`show system software images` lists that one image, no EVPN-capable alternative.

This is a **schema-level absence** — not configuration, not a licence toggle,
not something a bring-up would resolve. TC01/TC02/TC03 cannot execute on this
build, and nothing in the generated code is implicated.

It is consistent with the source documents: the SFS §8.1 "Development
Milestones" says only "See [Phases]", a document never supplied. The EVPN SFS
and CLI doc describe a feature still in development.

## Consequence

The 15 steps holding empty expectations stay open. They need real `show` output
from a box that runs EVPN:

- `show evpn global`
- `show evpn mac address-table`
- `show bgp l2vpn evpn table evi … detail`
- `show evpn bum routing-table`

**The ask is an EVPN-capable image, or a testbed running one — not more time on
3021.** Two open questions for Exaware:

1. Which release is EVPN targeted for, and on which platform? 3021 is edgeCore
   with an EC300Gig card; if EVPN is coming up on Jericho2, that is a different
   testbed.
2. Is there an `.ixncfg` with three traffic items where AC2 and AC3 source the
   same MACs (the local MAC-move case)? If not we build them in code via
   `CONFIGURE_NEW_TRAFFIC_ITEM`.

## Incidental finding: `origin` is reachable after all

`/auto/git/repos/auto.git` does **not** exist on the CodeValue dev box — which
is why the earlier M2 push failed — but it is **live on tate (10.1.70.200)**:
a bare repo, git 1.8.2.3, 271 branches, `auto_develop` at `5b7c8e9`. Branch
convention confirmed against real branches: `AUT-nnn-slug` and `EM-nnnn - desc`.
No EVPN branch exists yet.

So the suite can be pushed to Exaware's own repo from tate. It needs a ticket ID
so the branch lands as `AUT-nnn` / `EM-nnnn` rather than the provisional
`ate-m2-evpn-generated-suite`.

## Notes for whoever drives this CLI next

- Prompt is `router[<timestamp>]# ` (and `…(config)#`), **not** the `:>` that
  `CmpCliConnection` lists.
- Disable paging with `session screen-width 512 ; session screen-length 3200`.
- `exit` at the top level terminates the SSH session.
- Use `abort` to discard a private-config candidate without committing.
- The lab is unreachable from a laptop; drive it from the dev box, which needs
  the FortiClient VPN, which needs a FortiToken code per login.
