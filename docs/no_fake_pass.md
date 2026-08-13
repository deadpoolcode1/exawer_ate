# Pipeline rule: nothing may fake a pass

A generated test that reports success without checking anything is worse than
having no test at all. A red test gets fixed. A green test that checks nothing
gets **trusted** — and then quoted in a status report.

This is the companion rule to [anti_hallucination.md](anti_hallucination.md).
That one stops the pipeline inventing a command; this one stops it inventing
*confidence*.

## Why it exists

Every case below is real, from runs against SUT pc-3080 (8.7.0 LAB 22).

| What was reported | What had happened |
|---|---|
| `OK (1 test)` | Three configuration commands had been **rejected** by the CLI. Nothing was staged, so the commit had nothing to do, so `configAndValidate` logged a warning. |
| 7 usable expectations | Five were the MAC table's **legend** with no MAC address in it — text the device prints whether or not it ever learnt anything. |
| `Pass: no new Type-2 was triggered …` | An **empty** route table compared with an empty route table. |
| `Pass: … ended without errors` ×34 | The TCL library had never loaded. `configNewTrafficItem`, `trafficApply`, `startProtocols` all answered `invalid command name`. **No IXIA traffic was ever created.** |

None of these were caught by review. Each was caught by making the code read
something back and check it.

## The five controls

### 1. Generation stops on an expectation that could not fail

`ate/codegen/fake_pass.py` audits the suite before a line is emitted, and
raises `FakePassError` — the same posture `validate_grounding` takes towards an
ungrounded command. An expectation whose every line is a table rule, a column
header or a legend is rejected: it would match on a device where the feature
does nothing.

### 2. Generation reports what can actually fail

```
assertions: 2 of 19 verification steps can actually fail; 17 only warn
```

The headline number is never just the step count. A suite of thirty steps that
asserts nothing should look like what it is.

### 3. A test that verified nothing fails

Every emitted test class ends with:

```java
evpnUtils.assertSomethingWasVerified();
```

which fails the run with `INCONCLUSIVE: this test made no assertion that could
have failed` when no falsifiable assertion was made. Only assertions that could
have failed are counted — an expectation the device has never been asked for
warns, and a warning is not a check.

### 4. A no-change assertion refuses an empty baseline

"Nothing changed" is trivially true when there was nothing to change.
`verifyOutputUnchanged` reports `NOT ASSERTED` and does not count itself when
the snapshot was empty or said `No entries found`.

### 5. A rejected command fails its step

`EvpnUtils.configAndVerifyAccepted` checks the device's answer against
`GlobalParam.CLI_COMMAND_SYNTAX_ERROR_REGEXP` — Exaware's own pattern — before
committing, and `ate capture` refuses to record output with no state-bearing
content.

## The corollary, for anything that talks to a device

**"The call returned without error" is not evidence that it did anything. Read
something back.**

That is the only reason the IXIA problem was found: the generated code sets a
source MAC and then reads the attribute back rather than assuming the write
landed. The read came back empty, which turned a green run red, which led to 34
silent `invalid command name` answers, which led to the fact that no traffic had
ever been generated in any run of this suite.

## Verifying the rule still has teeth

A check that has never been seen to fail is not evidence. Each control has a
negative control that must reproduce:

| Control | How to make it fail |
|---|---|
| Rejected command | Set `AC_SUBINTERFACE` to `9999` (outside the device's `[1-4094]`) and re-run: `Tests run: 1, Failures: 1`. |
| Captured expectation | Change one captured line (`vlan-based` → `port-based`) and re-run: `is not as expected. Missing lines: [...]`. |
| Verified-nothing guard | Generate with `--captures ''` and re-run: `INCONCLUSIVE`. |
| Unfalsifiable expectation | `tests/test_codegen.py::test_an_expectation_of_pure_table_furniture_is_rejected`. |
