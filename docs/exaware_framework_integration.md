# Integrating with Exaware's JSystem framework (M2)

ATE's M2 output is Java that lands in **Exaware's own automation repo**. This
document records what that repo looks like, how to build against it, and what
the generator must emit to be accepted. It is the reference behind
`ate/codegen/`.

`.claude/skills/exaware-framework/SKILL.md` carries the same recipe in
operational form (that path is gitignored, so this file is the tracked copy).

---

## 1. The repo

`~/auto_develop_codevalue` on the dev box (`192.168.31.226`), reachable only
over the FortiClient VPN. Two Maven/Eclipse modules under an aggregator pom:

| Module | Files | Package |
|---|---|---|
| `cmp-infra-project` | 259 `.java` | `cmp.infra.*` — SUT / device / IXIA layer |
| `cmp-tests-project` | 688 `.java` | `cmp.tests.<suite>` — the tests |

Access notes that cost real time:

- The directory is **root-owned `drwx------`**. Reading needs `sudo`, and as
  `ilan` you cannot even `cd` into it — pass absolute paths to the sudo'd
  command.
- Shell globs expand *before* `sudo`, so `sudo ls $B/x/*.java` fails with a
  misleading "No directory". Use `find` under `sudo`.
- The box has **no JDK and no Maven**. It is a checkout host, not a build host.
- `origin` is `/auto/git/repos/auto.git/`, a filesystem path that does not
  resolve on the dev box, so **you cannot push from there**. Deliver a branch
  plus a `git bundle`.
- Branch / commit convention, from `git log`: `EM-nnnn - <description>` or
  `AUT-nnn-<slug>`. No git identity is configured on the box; recent authors
  use `<user>@<HOST>.cmpsys.com`.

## 2. Building against it

Mirror the sources and jars locally, then compile with a local JDK. JDK 17
handles the JDK-8-targeted tree via `--release 8`.

The in-repo `lib/` jars (117 of them: JSystem core, mibble, snmp4j, …) are
**not sufficient** — the poms also resolve from Maven Central and Exaware's
Nexus (`maven.top-q.co.il`). These must be added, and the versions matter:

| Artifact | Version | Why |
|---|---|---|
| `org.json:json` | 20201115 | the majority of missing-symbol errors |
| `org.apache.commons:commons-csv` | 1.7 | params CSV loaders |
| `com.google.code.gson:gson` | 2.8.9 | |
| `httpclient` / `httpcore` | 4.5.13 / 4.4.14 | `cmp.infra.RestClient` |
| `commons-logging` | 1.2 | httpclient transitive |
| **`org.apache.poi` (+ `-ooxml`, `-ooxml-schemas`)** | **3.17, not 4.x** | `HandleExcel` uses the POI 3.x `Cell.CELL_TYPE_*` int constants; POI 4 makes them a `CellType` enum and the build fails |
| `org.apache.xmlbeans:xmlbeans` | 3.1.0 | poi-ooxml transitive |
| `com.jcraft:jsch` | 0.1.55 | |
| `commons-collections` | 3.2.2 | |

```bash
CP=$(find libs extlibs -name '*.jar' | tr '\n' ':')
find <mirror>/cmp-infra-project/src/main/java <mirror>/cmp-tests-project/src \
     -name '*.java' > srcs.txt
javac --release 8 -nowarn -encoding UTF-8 -cp "$CP" -d build/classes @srcs.txt
```

**Baseline: 947 sources → 1448 classes, zero errors.** Anything else means the
classpath is wrong; do not start editing their code to make it build.

One genuine source fix is needed: `cmp/tests/multiCast/MultiCastParams.java`
carries a stray unused `import com.sun.javafx.collections.MappingChange;`. It
only ever compiled because Oracle JDK 8 shipped JavaFX internals. Fix it in the
local mirror; it is a real latent bug in their tree but does not belong in an
unrelated feature branch.

Compiling the generated files against `build/classes` is the **acceptance gate**
for M2 output. Generated Java that does not compile is not deliverable.

## 3. What a suite consists of

Modelled on `cmp/tests/vpls`, the closest analog to the M2 EVPN flows —
`TC05_VplsMacAgingTime` is a MAC-aging test driven by suspending and
unsuspending IXIA traffic items.

A suite is **four** artifacts, not one:

1. **`TCnn_<Name>.java`** — `extends CmpTestCase` (which extends JSystem's
   `SystemTestCase4`), one `@Test` method. Devices come from
   `getDevices().getCmpRouter(DevicesSut.CMP1)` and
   `getDevices().getIxiaRouter(DevicesSut.IXIA1)`. Steps are numbered report
   levels: `CompassReporter.stopAndStartLevel(++level + ". <text>")` — which
   maps 1:1 onto ATE `AtomicRow`s.
2. **`<Suite>Params.java`** — `implements ISuiteParams`; every expected value.
   This is the bulk of the real effort (`VplsParams.java` is **314 KB**) and
   therefore where the SOW's effort-reduction claim has to be earned.
3. **`<Suite>Utils.java`** — the verify helpers (`VplsUtils.java` is 190 KB).
4. **CLI command templates** — `NAME_$_$("cli text %s %s", SessionMode.X)`.

Verification comes in two styles: line-regex polling with
`CompassReporter.passFailByCondition` (see `ShowVplsDetail`), and structured
table query via `QueryObject` + `RowDataTable` (see `ShowIxiaStatistics`).
There are 135 `cmp/tests/common/query/compass/Show*.java` classes, one per show
command — and **none for EVPN**.

### Why `EvpnCommands` is a separate enum

`cmp.tests.common.Commands` is shared and 1220 lines, with **zero EVPN
entries** (only VPLS / VPWS / xconnect under `l2-services`). Every `CmpRouter`
entry point — `configAndValidate`, `runCommandAndSwitch*` — takes the
`ICmpCliCmd` *interface*, so a standalone `EvpnCommands` enum is a drop-in and
keeps the shared file free of merge conflicts against every other branch.

### IXIA

Driven **over TCL, not IxNetwork REST**: `cmp.infra.ixia.IxiaFunctions` wraps
tcl proc names through `cmp.infra.tcl.TclCli`. Traffic items are pre-built in
`.ixncfg` files loaded onto the chassis and tests suspend/unsuspend them —
though `IxiaFunctions.CONFIGURE_NEW_TRAFFIC_ITEM` exists if Exaware would
rather build them in code. `DevicesSut` declares a single `IXIA1`; ports are
vports inside it, so "1 DUT + 3 IXIA ports" needs no topology contortion.

## 4. Honesty boundary

Compilation is verifiable from a dev machine. **Execution is not** — that needs
the real DUT, the IXIA chassis and a bring-up SUT. Expected-value tables and
show-output parsers are guesses until validated against real device output.

`ate/codegen` therefore emits empty expectation arrays plus
`CompassReporter.warning(...)` for any step awaiting lab data, so an
unvalidated suite **cannot report a green run**, and `validate_grounding()`
raises if a CLI template has no documented origin. This is the posture of
`docs/anti_hallucination.md` and `ate/planner/cli_crosscheck.py`, carried from
the test plan into generated code.
