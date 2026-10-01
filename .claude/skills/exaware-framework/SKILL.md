---
name: exaware-framework
description: Reach, mirror, compile AND RUN Exaware's JSystem/Java automation framework (auto_develop_codevalue), and verify generated commands against the real DUT. Use whenever working on ATE M2+ code generation, selecting tests to generate, adding Commands/query classes, checking that generated Java compiles, or checking that generated CLI actually exists on the device.
---

# Exaware JSystem framework — access, mirror, compile

The ATE pipeline generates Java test code **into Exaware's own repo**. Nothing
should be handed over that has not compiled against the real framework. This
skill is the verified recipe for doing that from a dev machine.

## 1. Get on the network

The framework is only reachable over the FortiClient VPN. **The VPN can never
be unattended** — but not for the reason previously recorded here.

The gateway requires a **FortiToken one-time code** after the password:

```
Authentication Required
A FortiToken code is required for SSL-VPN login authentication.
FortiToken:
```

Saving the password with `-s` therefore does NOT make `axawear` unattended, and
`openfortivpn` fails for the same reason — its "Could not authenticate to
gateway" is the 2FA challenge, not a wrong password. Only the human has the
code, and the session expires, so expect to re-ask during long work.

The **cert `Confirm (y/n)` prompt IS automatable**, contrary to the older note
here. `forticlient-cli` reads it from `/dev/tty`, and `pty.fork()` gives the
child the pty as its *controlling* terminal, so the write lands. A working
driver lives in the session scratchpad pattern:

```python
pid, fd = pty.fork()
if pid == 0:
    os.execv("/opt/forticlient/forticlient-cli",
             ["forticlient-cli", "vpn", "connect", "axawear", "-u", "ilan", "-s"])
# then respond to "Confirm (y/n)", "FortiToken:", "Password:" as they appear
```

So: automate the confirm, ask the human only for the six digits. Verify before
trusting a "connected" claim — the CLI status and a tunnel interface must both
agree:

```bash
/opt/forticlient/forticlient-cli vpn status     # want: Status: Connected
ip route get 192.168.31.226                     # must NOT go via the LAN gateway
ssh -o BatchMode=yes -o ConnectTimeout=10 axawear hostname
```

## 2. Read the repo (needs sudo)

`~/auto_develop_codevalue` on the dev box is **root-owned `drwx------`**. As
`ilan` you cannot even `cd` into it. Use absolute paths under sudo:

```bash
ssh axawear 'S() { echo "$PW" | sudo -S -p "" "$@"; }; S find /home/ilan/auto_develop_codevalue -name "*.java"'
```

Two gotchas that cost time:
- `cd $B && S find ...` fails — the `cd` runs as `ilan`, before sudo. Always
  pass absolute paths to the sudo'd command.
- Globs (`S ls $B/x/*.java`) expand in the *local* shell before sudo, so they
  hit the permission error and print "No directory". Use `find` under sudo.

## 3. Mirror it locally

Compiling on the dev box is impossible — **it has no JDK and no Maven**. Mirror
the sources and the jars to a scratch dir instead:

```bash
# sources (~49 MB, 947 .java)
ssh axawear 'echo "$PW" | sudo -S -p "" tar czf /tmp/fw.tgz -C /home/ilan/auto_develop_codevalue \
  --exclude=.git --exclude="*/target/*" --exclude="*.jar" --exclude="*.ixncfg" \
  cmp-infra-project/src cmp-tests-project/src */pom.xml pom.xml; \
  echo "$PW" | sudo -S -p "" chmod 644 /tmp/fw.tgz'
scp axawear:/tmp/fw.tgz "$SCRATCH/"

# the 117 in-repo jars (JSystem core, mibble, snmp4j, …)
# same pattern with: find … -name "*.jar" -printf "%P\n"
```

## 4. Complete the classpath

The in-repo `lib/` jars are **not sufficient** — the poms also pull from Maven
Central / their Nexus (`maven.top-q.co.il`). Fetch these from Central; the
versions matter:

| Artifact | Version | Why |
|---|---|---|
| `org.json:json` | 20201115 | 153 of the missing-symbol errors |
| `org.apache.commons:commons-csv` | 1.7 | params CSV loaders |
| `com.google.code.gson:gson` | 2.8.9 | |
| `org.apache.httpcomponents:httpclient` / `httpcore` | 4.5.13 / 4.4.14 | `RestClient` |
| `commons-logging` | 1.2 | httpclient transitive |
| **`org.apache.poi:poi` + `poi-ooxml` + `poi-ooxml-schemas`** | **3.17 — not 4.x** | `HandleExcel` uses `Cell.CELL_TYPE_NUMERIC`, the POI 3.x int constants. POI 4 turns these into a `CellType` enum and the build fails with "enum switch case label must be the unqualified name". |
| `org.apache.xmlbeans:xmlbeans` | 3.1.0 | poi-ooxml transitive |
| `com.jcraft:jsch` | 0.1.55 | |
| `commons-collections` | 3.2.2 | |

## 5. Compile

Local JDK 17 compiles the JDK-8-targeted tree fine with `--release 8`:

```bash
CP=$(find libs extlibs -name '*.jar' | tr '\n' ':')
find fw/cmp-infra-project/src/main/java fw/cmp-tests-project/src -name '*.java' > srcs.txt
javac --release 8 -nowarn -encoding UTF-8 -cp "$CP" -d build/classes @srcs.txt
```

**Baseline: 947 sources → 1448 classes, zero errors.** If you see errors other
than the one below, your classpath is wrong — do not start editing their code.

One genuine source fix is required: `cmp/tests/multiCast/MultiCastParams.java`
has a stray unused `import com.sun.javafx.collections.MappingChange;` (an IDE
auto-import). It only ever compiled because Oracle JDK 8 shipped JavaFX
internals. Delete the line in the local mirror. It is a real latent bug in their
tree — mention it, don't silently ship a fix in an unrelated branch.

Regenerate `build/classes` and re-run this compile as the **acceptance gate for
every generated file**: generated Java that does not compile is not deliverable.

## 6. What generated code must look like

See [[project-m2-jsystem-framework]] in memory for the full idiom notes. The
short version — a generated suite is **four** artifacts, not one:

1. `TCnn_<Name>.java` — `extends CmpTestCase`, one `@Test`, steps rendered as
   `CompassReporter.stopAndStartLevel(++n + ". <text>")` (maps 1:1 onto ATE
   `AtomicRow`s).
2. `<Suite>Params.java` — every expected value as constants/tables. This is the
   bulk (`VplsParams.java` is 314 KB) and where the effort saving lives.
3. `<Suite>Utils.java` — verify helpers.
4. Additions to `cmp.tests.common.Commands` — the shared enum of
   `NAME_$_$("cli text %s %s", SessionMode.CLI_CONFIGURE)` templates, plus new
   `cmp/tests/common/query/compass/Show*.java` classes. **`Commands` is shared
   and 1220 lines — appending to it is a merge point with their team.**

## 7. Delivering a branch

- Branch/commit convention from `git log`: `EM-9531 - <description>` or
  `AUT-nnn-<slug>`. Ask for the ticket ID; don't invent one.
- Current branch is `auto_develop`; the working tree is already dirty with
  `CSV Parser/.idea/*` noise — scope any `git add` to your own paths.
- **`origin` is `/auto/git/repos/auto.git/`, a filesystem path that does not
  exist on the dev box.** You cannot push from there. Deliver as a local branch
  plus a `git bundle`, or have the user push from a machine that mounts it.
- Never put Claude/Anthropic/AI attribution in commit messages (see
  [[feedback-no-claude-attribution-in-commits]]).

## 8. Running it — you CAN, and you should

The old note here said "you can compile, you cannot run". That is no longer
true and it was costing us the only feedback that catches real errors.

### Run the JVM on the DEV BOX, not the laptop

This is the recipe that works, and it removes the tunnel entirely.

The DUT subnet is routable **only from the dev box**, and `CliConnectionImpl`
constructs `new SSH(host, user, password)` — the three-argument form — so the
CLI port really is hardcoded to 22 and `setPort` is ignored on that path
(verified by disassembling `cli-6.1.10.jar`). From a laptop that forces an
iptables DNAT onto a loopback alias, which needs **root you may not have**. The
dev box reaches `10.3.80.1:22` directly.

The dev box has no JDK, so bring your own, in ilan's home — no sudo, nothing
installed system-wide:

```bash
curl -fsSLO https://github.com/adoptium/temurin17-binaries/releases/download/\
jdk-17.0.13%2B11/OpenJDK17U-jdk_x64_linux_hotspot_17.0.13_11.tar.gz
scp OpenJDK17U-*.tar.gz axawear:~/ate-run/jdk17.tgz
ssh axawear 'mkdir -p ~/ate-run/jdk17 && tar xzf ~/ate-run/jdk17.tgz \
             -C ~/ate-run/jdk17 --strip-components=1'
```

The laptop DNAT recipe still works if you do have root; keep it as the fallback:

```bash
ssh -N -f -L 12221:10.3.80.1:22 axawear
sudo sysctl -w net.ipv4.conf.all.route_localnet=1
sudo iptables -t nat -A OUTPUT -p tcp -d 127.0.0.3 --dport 22 \
     -j DNAT --to-destination 127.0.0.1:12221   # point cmp1's host at 127.0.0.3
```

### Running a test

```bash
CP=$(find libs extlibs -name '*.jar' | tr '\n' ':')build/classes
cd run && java -cp "$CP" org.junit.runner.JUnitCore cmp.tests.evpn.TC01_...
```

Five environment facts, each of which cost a run before it was known:

* **The SUT file is resolved under `tests.dir`/sut**, not `sut.dir`. Setting
  only `sut.dir` gets you `WARNING: SUT directory … couldn't be found` followed
  by a silent fallback to `default.xml`, and then `Fail to init system object:
  cmp1`. Put the `sut/` directory (with its `envir/` includes) inside
  `tests.dir` as well.
* **JSystem rewrites `jsystem.properties` on startup**, including `sutFile`.
  Check what it left behind before believing your own settings.
* `GlobalUtils.getCurrentWS()` is the **parent of the working directory**, so
  `bringUpParams.crt` and `configurations/` must sit at
  `<parent>/cmp-tests-project/src/cmp/tests/<suite>/`.
* Two directories must exist or bring-up dies writing files:
  `<ws>/run/tempfiles/` and
  `<ws>/cmp-infra-project/src/main/java/cmp/infra/config/exawareCfg/exaSystem/`
  (the path comes from the config class's own package). Copy the whole
  `cmp-infra-project/src` and `cmp-tests-project/src` trees into the workspace
  and the TCL library lands in the right place too — otherwise every
  `IxiaFunctions` call answers `invalid command name`.
* **JDK 17 removed JAXB**, which the JUnit reporter needs: add `jaxb-api`,
  `jaxb-runtime`, `jaxb-impl`, `jaxb-core` and `activation` to the classpath or
  every test ends with `NoClassDefFoundError: javax/xml/bind/JAXBContext`.

### Deploy and run a generated suite (the routine loop)

The dev box workspace is `/var/tmp/ate-run`. One script does deploy, compile,
`.crt` check and the detached run, and **stops before any TC on a javac or
`.crt` failure** (2026-10-01: a hand-typed one-liner ran the TCs on stale
classes after javac failed):

```bash
ate codegen --lab 3ac-core --ixncfg EVPN_3AC_CORE.ixncfg --ac-vlans 1001,1002,1003 \
    --captures deliverables/M2/evidence_captured_expectations_3ac_core.json -o $GEN
cp deliverables/M2/generated_suite/cmp/tests/evpn/configurations/ixia/EVPN_3AC_CORE.ixncfg \
   $GEN/cmp/tests/evpn/configurations/ixia/
scripts/lab/deploy_suite.sh $GEN TC01_EvpnVlanBasedBringUp TC02_EvpnType2MacIpAdvertisement TC03_EvpnType3ImetFlooding
```

* Each TC runs from its own reboot (`cycle.sh`); `run_with_retry.sh` retries
  only runs that died in **bring-up** (no numbered step reached), never a
  failed step. About half the pc-3080 bring-ups die on the serial console
  (stray `router#` prompt, or `Wanted mode: ONL` in `checkCoresAndAlarms`).
* The run is `nohup` on the dev box and survives a VPN drop. Wait with a loop
  that tolerates ssh failures:
  `until timeout 30 ssh axawear 'grep -q ALL_DONE /tmp/run_<date>.log'; do sleep 60; done`.
* Results: `/tmp/<TC>_clean.log` (`OK (1 test)` / `Fail:` lines), reports in
  `run/log/report_<TC>/`. Merge with `scripts/lab/merge_reports.py`, check
  with `scripts/verify_automation_report.py <report> deliverables/M2/generated_suite`.

### Framework traps found by running

* **Command enums are mutable singletons.** `EvpnCommands.X.args(...)` sets the
  arguments on the enum constant and returns it, so three `X.args()` in one
  varargs call are one object with the last arguments (pc-3080, 2026-10-01:
  AC3 bound three times, AC1/AC2 never). Pass one command per call.
* `"\n"` inside a Python template that emits Java must be `"\\n"`, or javac
  sees an unclosed string literal. Unit tests on the generated text do not
  compile it; `test_no_java_string_literal_spans_a_line` now catches this one.

### What bring-up needs that a mirror does not have

Bring-up validates `bringUpParams.crt` against a stored response template under
**`/auto/automation/Jsystem/ResponseTemplates/`** (`bringUpParameters_C0_00*.crt`)
— an NFS path that exists on **tate (10.1.70.200)**, not on the dev box. Copy
the directory to that exact local path; `GlobalParam` hardcodes it.

That template is **position-sensitive**: it pins the section comments, the blank
lines between them, and six tables in order. A `//` comment inside a table
shifts the static blocks and merges the following header into one column, and
the whole file is rejected with "format doesn't match the template". Validate
your emitted file directly rather than guessing:

```java
TemplateManager.getInstance().validateAgainstTemplate(
    "bringUpParameters", "", DeviceType.COMPASS, OutputAnalyzer.analyze(text));
```

Beyond that, a full bring-up reaches the terminal server on tate, the DUT's
serial console and PDU, and ONL-level network setup — it needs site config and
ONL images that live on their runner. Expect to stop there.

## 9. Verify generated CLI against the device

Compiling proves the Java is valid. It says nothing about whether the commands
exist. Use the pipeline's own stages:

```bash
ate verify-commands --host 10.3.21.1 --jump ilan@192.168.31.226
ate capture         --host 10.3.21.1 --jump ilan@192.168.31.226
```

`verify-commands` probes by **CLI completion, never by execution** — running
registry entries blind would mean firing `clear` and config commands at a live
device to see whether they parse. Two traps, both of which produced a report
full of false "missing" verdicts before they were fixed:

- A `?` on a config path both LISTS and DESCENDS, and the descent creates the
  node in the candidate configuration. Give **each config probe its own
  `configure` / `abort` cycle**; sharing one session lets the candidate
  accumulate until completions stop reflecting a clean device.
- Drain the channel before every send, or the reader matches a prompt left over
  from the previous probe and attributes answers to the wrong command.
- **A `?` on a LEAF does not list-and-return — it opens an interactive value
  prompt**, and no `#` is coming:

  ```
  l2-services evpn X service-type ?
  Possible completions:
    vlan-based
    port-based[vlan-based]
  [port-based,vlan-based]:            <- the device is waiting for a VALUE
  ```

  Range leaves do the same with parentheses, over several lines:
  `(<1-250000>    maximum MAC learned (default 65520)\n  Currently configured): `.
  This was the real cause of the "configuration half is untrustworthy" era: the
  reader waited out its full timeout, returned a partial buffer, and the answer
  stayed in the channel for the NEXT probe to collect — so every later verdict
  described the wrong command. Escape with **Ctrl-C** (`\x03`), which answers
  `Error: user aborted` and returns to the prompt. **Never answer the prompt** —
  answering is a write to a live device. Then *prove* the channel resynced
  before the next probe rather than assuming it.

Three verdict rules that keep the report honest:

- A placeholder that must name an existing object (`evi-name X`) yields a false
  "missing" until that object exists. Worse, where the placeholder is not a
  legal key the device says `syntax error: "X" is not a valid value` and the
  node was never reached — that is **`unknown`, not `missing`**. `af-l2vpn
  evpn` was reported missing this way on a build that has it.
- The device appends a leaf's CURRENT value to its own name with no separator:
  `port-based[vlan-based]` is the token `port-based`. Compared raw it never
  matches, and a correct command reads as missing.
- An argument spelled `<value>` rather than `%s` is still an argument. Probing
  for a literal `<value>` token can only ever report missing, on every device.

**paramiko must be pinned `<3.0`** (`pip install 'paramiko>=2.9,<3.0'`).
paramiko 3+ dropped SHA-1 `ssh-rsa` host keys, which is the only host-key
algorithm this lab's routers offer.

## 10. Device output outranks documents — the standing example

We resolved `show evpn mac address-table` in favour of the SPACE using three
agreeing sources: the `clear` syntax in the same CLI doc, the VPLS family in
the Command Reference Guide, and Exaware's own production `Commands` enum. The
device rejects it. `show evpn ?` offers `mac-address-table`, with a HYPHEN.

Then we propagated that "fix" onto the `clear` form and broke it, because
`clear evpn ?` → `mac` → `address-table` — the **space**. The product simply
uses different spellings for the two commands, and each CLI-doc cell was right
about its own command.

Other corrections the device made, all on 8.7.0 LAB 22:

| Documented | Actual |
|---|---|
| `show evpn global` | does not exist — `summary` / `detail` |
| `show evpn bum routing-table` | does not exist — `broadcast-domains` carries the BUM label |
| `l2-services evpn <n> import-rt` | lives under `auto-discovery` |
| `show interface ... detail` | no `detail` under `show interface` |
| `show bgp l2vpn evpn table evi evi-name <n>` | only the bare `... table evi [detail]` form works without BGP state |

And from running the suite on pc-3080 (same 8.7.0 LAB 22):

| Documented / assumed | Actual |
|---|---|
| a vlan-based EVI binds the AC interface | **it refuses a port** — "is not a sub-interface, but the EVPN service-type is vlan-based". ACs must be sub-interfaces: `interface intN.100` / `l2-transport enable` |
| `l2-services evpn <n>` has ~9 knobs | **five**: `auto-discovery`, `interface`, `mac-aging-time`, `mac-limit`, `service-type` |
| `interface agg-eth <n> ethernet-segment ...` | no `ethernet-segment` node under an interface at all |
| `service-type vlan-aware-bundle` / `vlan-bundle` | only `port-based` / `vlan-based` |
| `mac-limit` default 250000 | range `<1-250000>`, **default 65520** |
| `af-l2vpn evpn` under BGP or a VRF | only under a **neighbour / neighbour-group**, and only in **`vrf default`** |

**Name the build in every claim.** pc-3021 was re-imaged mid-session from LAB
904 (no EVPN in the data model at all) to LAB 22 (EVPN present), and the two
disagreed about whether the feature existed.

**Do not assume the prompt shape either.** pc-3021 shows
`router[2026-08-11-18:38:07]#`, pc-3080 a bare `router#` — and the *same* DUT
switched to the timestamped form after a bring-up loaded its config. A reader
that requires the `]` hangs on every read instead of failing, which is worse.

### The false-green class of bug — check for it deliberately

Two ways a run reported success while doing nothing, both found on pc-3080:

* **A rejected configuration command left the test green.** `configAndValidate`
  runs the command, then commits. A command the CLI refuses stages nothing, so
  the commit has nothing to do, so the framework reports a *warning*. Generated
  config steps must assert acceptance themselves (check the output against
  `GlobalParam.CLI_COMMAND_SYNTAX_ERROR_REGEXP`) before committing.
* **A captured "expectation" that could never fail.** `show evpn
  mac-address-table` prints its legend whether or not a single MAC was learnt,
  so recording the legend as the expected output yields an assertion that passes
  on a broken device. `capture` now rejects a MAC table with no MAC in it.

Whenever you add a check, **make it fail once on purpose.** The sub-interface
assertion was proved by rebuilding with `AC_SUBINTERFACE = 9999` (outside the
device's `[1-4094]`) and watching the same run turn red. A check that has never
been seen to fail is not yet evidence of anything.

## 11. IXIA traffic without an .ixncfg

Their suites load prebuilt binary `.ixncfg` files and only suspend/unsuspend
what those contain. You cannot synthesise that format — but you do not need to.
`IxiaFunctions` exposes the whole build API over TCL:
`configNewTrafficItem` → `configTrafficItemEndpoints` → `configTrafficItemStream`
→ `configTrafficItemFrameRate` → `applyTraffic`.

Argument order is positional; verify it against the **proc signatures** in
`cmp-infra-project/src/main/java/cmp/infra/tcl/ixia_lib.tcl`, not against the
`$arg` help strings in the enum.

**Known limit:** that library has `editTrafficRawDestMacAddr` and *no source
equivalent*, while EVPN learns from SOURCE MACs. Anything requiring two ports
to emit the same source MAC — the local MAC-move case — still needs either an
`.ixncfg` or a new proc in `ixia_lib.tcl`. That is Exaware's file; flag it,
don't edit it inside a feature branch.

## 12. Honesty boundary

Expected-value tables and show-output parsers are guesses **until captured from
a device**. `ate capture` fills them from real output and refuses to record a
rejection or an empty table as an expectation — a test that passes by asserting
a feature is absent is worse than no test.

Mark what has not been validated. The anti-hallucination posture in
`docs/anti_hallucination.md` applies to generated Java exactly as it does to the
test plan, and to this skill's own claims: two statements in earlier versions of
this file ("the VPN cert prompt cannot be automated", "you cannot run") were
wrong and cost real time.
