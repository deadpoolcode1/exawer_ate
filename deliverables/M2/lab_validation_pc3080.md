# Lab validation — SUT pc-3080

Yuval Hoffman reserved **pc-3080** in place of pc-3021 for this activity
(2026-08-12). This is the record of what the rig is and what running against it
changed. It supersedes `lab_validation_pc3021.md` for anything about EVPN
behaviour; keep that file for the pc-3021 rig details.

## The rig

JSystem SUT file `cmp-tests-project/src/main/resources/sut/pc3080.xml`.

| | |
|---|---|
| DUT `CMP1` | `exa-il01-uf-3080`, mgmt **10.3.80.1**, `admin`/`admin` |
| Platform | `Type=UfiSpace`, lc0 `lcType=800GigCombo` (pc-3021 was `edgeCore` / `EC300Gig`) |
| Software | **8.7.0 LAB 22**, app build `feature/dev64_evpn_23Jul2026@43f66a385b`, Data Model 7, ConfD 5.0.7.5 |
| ONL | 10.3.80.10 |
| IXIA app server | 10.1.70.200 (`tate`) · chassis 10.1.70.108 · **ixiaIp 10.1.90.80** |
| IXIA vports | pool `data1`: vport1 = card 5/1, vport2 = card 5/2, vport3 = card 6/8 |
| DUT AC ports | pool `data1`: `x-eth 0/0/8`, `x-eth 0/0/18`, `x-eth 0/0/26` |
| VLAN | `general/vlans[0]` = **3380** |
| Extras pc-3021 lacked | a Juniper router (`jr1`, 10.1.68.179) and two Linux servers |

Alarm history is **clean** — `show system alarm history | include Raised`
returns nothing. The standing `PSU PSU-1 is Failed` caveat from pc-3021 does not
apply here.

## The headline

**TC01 runs green, end to end, on this hardware.** `OK (1 test)`, exit 0,
including a complete bring-up — which is what pc-3021 could not reach. Detail
and the negative control are in `evidence_tc01_run_pc3080.txt`.

## What the device corrected

Every row below was found by running, not by reading. None of it is in the SFS
or the EVPN CLI doc.

| We had | 8.7.0 LAB 22 says |
|---|---|
| A vlan-based EVI binds the AC port | **It does not** — the commit is rejected: "is not a sub-interface, but the EVPN service-type is vlan-based". The AC must be a sub-interface (`x-eth 0/0/8.100`, `l2-transport enable`) |
| `l2-services evpn <n>` has knobs for `control-word`, `host mac-address-duplicate-detection`, `Advertise-mac`, `unknow-mac-flooding`, `es-waiting-time` | The node offers **five** children only: `auto-discovery`, `interface`, `mac-aging-time`, `mac-limit`, `service-type`. (`show evpn detail` *displays* control-word and duplicate-detection state, so they exist as read-only status, not as configuration here.) |
| `interface agg-eth <n> ethernet-segment …`, `lacp-key`, `lacp-system-mac` | No `ethernet-segment` node under an interface at all — the EVPN multi-homing configuration is absent from this build |
| `service-type` accepts `vlan-aware-bundle` / `vlan-bundle` | Only `port-based` and `vlan-based` |
| `mac-limit` default 250000 (used by FLOW-080) | Range `<1-250000>`, **default 65520**. 250000 is the configurable maximum |
| BGP EVPN address family | `af-l2vpn evpn` exists **only under a neighbour or neighbour-group, and only in `vrf default`**. It is not a VRF-level node, and it does not appear under a non-default VRF |
| `show bgp table l2vpn …` | Offers `vpls` only; the EVPN table is reached as `show bgp l2vpn evpn …` |

Carried over from pc-3021 and re-confirmed here: `show evpn mac-address-table`
(hyphen) versus `clear evpn mac address-table` (space) — the product really does
spell the two commands differently, and each CLI-doc cell was right about its
own command.

## What running against a second box changed in our tooling

Three defects only a different testbed could expose. All three are fixed, with
regression tests.

1. **The CLI prompt shape was assumed.** pc-3021 shows
   `router[2026-08-11-18:38:07]#`; pc-3080 shows a bare `router#`. The reader
   required the `]`, so on pc-3080 *no read ever terminated*: every probe burned
   its full timeout and returned a partial buffer, and `verify-commands` and
   `capture` hung rather than failed. The timestamp is a per-box CLI setting —
   the same DUT started showing the timestamped form later the same night, once
   the bring-up config had been loaded.

2. **The configuration half of `verify-commands` was untrustworthy, and now the
   reason is known.** A `?` on a *leaf* does not list-and-return; the device
   drops into an interactive prompt for the value:

   ```
   l2-services evpn X service-type ?
   Possible completions:
     vlan-based
     port-based[vlan-based]
   [port-based,vlan-based]:            <- waiting; no prompt is coming
   ```

   The reader waited out its timeout, and the answer sat in the channel until
   the *next* probe collected it — so every later verdict described the wrong
   command. That is why `mac-limit` was once reported missing on a device that
   demonstrably has it. Fixed by recognising a value prompt as "the device is
   waiting", escaping it with Ctrl-C (never by answering — answering is a write
   to a live device), and re-checking after every probe that the channel is back
   at its prompt. The sweep now reports how many times it had to recover; on the
   full run it was **0**.

3. **A probe that cannot be asked is now `unknown`, not `missing`.** Where the
   placeholder is not a legal key the device says so —
   `syntax error: "X" is not a valid value` — and the node under test was never
   reached. Reporting that as missing sends someone to fix a command that is
   correct. Related: templates that spell an argument `<value>` rather than `%s`
   were being probed for a literal token `<value>`, which no device will ever
   offer; those five could only ever report missing.

## Still open, and not ours to close

| # | Item | Effect |
|---|---|---|
| 1 | **A source-MAC proc in `ixia_lib.tcl`** (or an `.ixncfg` with the three items) | No traffic EVPN can learn from → 9 of 11 expectations stay uncaptured, and the MAC-move premise of FLOW-030 cannot be expressed |
| 2 | **A BGP EVPN peer** for this DUT | The four `show bgp l2vpn evpn table evi detail` expectations have nothing to show |
| 3 | **A ticket ID** (`AUT-nnn` / `EM-nnnn`) | The branch cannot land under its real name |
| 4 | **Confirmation on the absent EVI knobs and multi-homing config** | Either the CLI doc is ahead of the build, or the build is missing them — we report, we do not guess |
