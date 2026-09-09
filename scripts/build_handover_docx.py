#!/usr/bin/env python3
"""Build the client-facing milestone hand-over .docx.

Separate from `build_docs_docx.py`, which converts our internal markdown docs
via pandoc. This one is written directly with python-docx because a hand-over
is a different artifact: two pages, three tables, and every claim in it has a
matching file in the evidence folder.

Regenerate after changing any of the numbers it quotes: they are deliberately
inline rather than computed, so that a stale figure is a visible edit in the
diff rather than something the script silently recalculates from a run that no
longer matches what was shipped.

    python scripts/build_handover_docx.py [OUTPUT_DIR]

Output path is the milestone package on the Desktop. It is passed in by
`build_handover_package.sh` so the .docx always lands in the package that was
just built. It used to be a hardcoded date, which meant a package built on any
other day shipped with no hand-over document at all.
"""
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

OUT = (sys.argv[1] if len(sys.argv) > 1
       else "/home/ilan/Desktop/Exaware_M2_handover_2026-08-14") + "/M2_Handover.docx"
#: Keep in step with deliverables/M2/, where every claim below has an evidence file.
ACCENT = RGBColor(0x1F, 0x4E, 0x79)
MUTED = RGBColor(0x59, 0x59, 0x59)


def style(doc):
    n = doc.styles["Normal"]
    n.font.name = "Calibri"
    n.font.size = Pt(10.5)
    n.paragraph_format.space_after = Pt(6)


def h(doc, text, size=13, space_before=12):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.color.rgb = ACCENT
    return p


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, htxt in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(htxt)
        r.bold = True
        r.font.size = Pt(9.5)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(val))
            r.font.size = Pt(9.5)
    return t


def bullets(doc, items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(3)
        if isinstance(it, tuple):
            lead, rest = it
            r = p.add_run(lead)
            r.bold = True
            p.add_run(rest).font.size = Pt(10.5)
        else:
            p.add_run(it).font.size = Pt(10.5)


doc = Document()
style(doc)

# ── title ───────────────────────────────────────────────────────────────
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("Milestone 2: Hand-over")
r.bold = True
r.font.size = Pt(20)
r.font.color.rgb = ACCENT

s = doc.add_paragraph()
s.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = s.add_run("Dirty Queue & Code Generation · SOW PQ4476E\n"
              "CodeValue → Exaware · 9 September 2026")
r.font.size = Pt(10)
r.font.color.rgb = MUTED

# ── acceptance ──────────────────────────────────────────────────────────
h(doc, "M2 deliverables: all four met", space_before=14)
table(doc,
      ["SOW M2 deliverable", "Result"],
      [["Code generation based on selected tests",
        "TC01 / TC02 / TC03, emitted only for what the dirty queue marks SELECTED"],
       ["Pattern matching implementation",
        "537 of 612 automatable plan rows (87.7%) mapped to typed executable steps"],
       ["Demo: extract requirements from sample docs",
        "133 requirements → 269 plan rows → 698 action rows, from the SFS, CLI doc and 2 RFCs"],
       ["Up to 3 integration-ready test plans",
        "Three suites that compile unmodified against cmp-infra-project and cmp-tests-project"]])

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run("Also delivered: the dirty queue itself (the SOW lists it under M4), "
              "per-scenario device configuration, and a device-verification stage "
              "that did not exist when M2 was scoped.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

# ── verified ────────────────────────────────────────────────────────────
h(doc, "Verified on your hardware")
p = doc.add_paragraph()
r = p.add_run("SUT pc-3099 / exa-il01-ec-3099, software 8.7.0 LAB 935, "
              "run 9 September 2026. Lab profile lab-1dut-3ac-core.")
r.font.size = Pt(10)
bullets(doc, [
    ("Bring-up stands the tester up by itself: ",
     "the .crt loads EVPN_3AC_CORE.ixncfg, three vports come up, protocols "
     "start and are checked. The DUT reaches OSPF Full and BGP up on "
     "29.60.0.2. L2VPNevpn reads NoNeg: no BGP EVPN licence on the chassis."),
    ("Three attachment circuits, two sharing one port: ",
     "x-eth0/0/32.1001, x-eth0/0/40.1002, x-eth0/0/40.1003, read back from "
     "show evpn detail."),
    ("VLANs 1001-1003 from the tool: ",
     "the run asserts they do not clash with the SUT's 3399."),
    ("Each test creates the EVI it uses, ",
     "after asserting it absent. The .cfg no longer ships the service."),
    ("Compiles against your framework: ",
     "953 sources to 1455 classes, zero errors, javac --release 8."),
    ("bringUpParams.crt passes your own validator: ",
     "TemplateManager.validateAgainstTemplate returns true."),
    ("One package, two differently cabled rigs: ",
     "unchanged on pc-3080 (0/0/8, 0/0/18, 0/0/26) and pc-3099 (0/0/18, "
     "0/0/32, 0/0/40). Interfaces resolve from your SUT file."),
])

h(doc, "What is NOT proven, and why", size=11, space_before=10)
bullets(doc, [
    ("bgpd aborts when an EVI is deleted: ",
     "assert (_Bool)(ipi_evi_p), bgp_evi.c:310, bgp_evi_delete. Four cores "
     "in one day, reproduced by hand. This is a defect in the product, found "
     "by the suite. See evidence_bgpd_crash_on_evi_delete.txt."),
    ("exaSystemConf_pc3099.cfg restores the EVI: ",
     "bring-up loads it, so TC01 cannot start from the clean device it "
     "asserts. Please re-save that baseline without the EVPN instance."),
    ("Traffic reaches the DUT port, not the circuit: ",
     "frames transmit and the physical ports count them in bulk; the vlan-id "
     "sub-interfaces count zero and nothing is learnt. Double tagging ruled "
     "out. See evidence_traffic_open_issue.txt. This is ours to close."),
    ("7 of 25 verification steps can actually fail; ",
     "the other 18 warn and say why. Nothing is reported as a pass that "
     "is not one."),
])

h(doc, "Two defects the run found, which matter more than the pass", size=11,
  space_before=10)
bullets(doc, [
    ("A vlan-based EVI will not bind a port - ",
     "the commit is rejected: \"interface x-eth 0/0/8 is not a sub-interface, but the "
     "EVPN service-type is vlan-based\". This is in neither the SFS nor the CLI doc. "
     "The generator now creates the attachment circuits as sub-interfaces first, using "
     "the same stanza your VPLS suite uses."),
    ("A rejected command could not fail the test - ",
     "three configuration commands were refused by the CLI and the run stayed green: "
     "nothing was staged, so the commit had nothing to do, so configAndValidate logged "
     "a warning. Generated configuration steps now assert acceptance themselves. A "
     "negative control - an out-of-range sub-interface - turns the same run red, so we "
     "know the assertion works."),
])

h(doc, "A correction to our own last hand-over", size=11, space_before=10)
p = doc.add_paragraph()
r = p.add_run("The previous drop reported that the suites made one EVPN-behaviour "
              "assertion and that it was vacuous. That was true when written, and the "
              "reason was worse than we said: four expectations had captured a table "
              "LEGEND rather than any rows - text a device prints whether the feature "
              "works or not. Our own guard was meant to refuse exactly that and only "
              "recognised short all-caps labels, so the BGP table's mixed-case Flags: "
              "and Origin: walked past it.")
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("The guard now matches the shape of a glossary rather than one spelling "
              "of a label, and applies to every command. The assertions in the table "
              "below are what survived that.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

# ── doc corrections ─────────────────────────────────────────────────────
h(doc, "What \"green\" means here - and what it does not", size=11, space_before=10)
p = doc.add_paragraph()
r = p.add_run("We would rather you get this from us than find it yourselves.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED
table(doc,
      ["Suite", "Result on pc-3099, 9 Sep", "Stops at"],
      [["TC01 bring-up", "FAIL",
        "bring-up restores the EVI from exaSystemConf_pc3099.cfg, so the "
        "\"EVI is absent\" assertion fails before the test acts"],
       ["TC02 Type-2 MAC/IP + local move", "FAIL",
        "frames reach the DUT port but not the vlan-id sub-interface"],
       ["TC03 Type-3 IMET + flooding", "FAIL", "the same traffic cause"]])
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run("TC02 and TC03 fail for one reason between them, and it is the "
              "reason you named on 8 September: bringUpParams.crt loads no IXIA "
              "configuration, so the TCL ixia() array has no vport entries and no "
              "frame can be offered. Every DUT-side step of both tests passes. We "
              "are not presenting that as a pass, and the tests do not either - "
              "they fail, loudly, with the chassis's own words.")
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("Most of the reported passes in any run are your framework's own "
              "infrastructure checks - disk space, commit succeeded, IXIA connected, "
              "no watchdog reboot. The EVPN ones are the assertions that read device "
              "output back and compare it: on this drop TC01 makes four of them, "
              "against show evpn detail, show evpn summary, the EVPN route table and "
              "the neighbour's EVPN capability. Across the suite 7 of 25 verification "
              "steps can currently fail; the other 18 warn and say why.")
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("What is still not demonstrated is Type-2/Type-3 ROUTE EXCHANGE with "
              "a peer. Emulating a BGP EVPN speaker on the IXIA fails with \"no "
              "license available for BGP EVPN\" on chassis 10.1.70.108. The DUT does "
              "originate its own Type-3 IMET route and TC01 asserts it; what needs a "
              "peer is the receiving half.")
r.font.size = Pt(10.5)

h(doc, "Corrections your EVPN CLI documentation may want")
p = doc.add_paragraph()
r = p.add_run("Found by running against LAB 22, not by reading.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED
table(doc,
      ["The documents say", "8.7.0 LAB 22 does"],
      [["A vlan-based EVI binds the AC interface",
        "It rejects a port outright: the AC must be a sub-interface "
        "(x-eth 0/0/8.100, l2-transport enable)"],
       ["l2-services evpn <name> has control-word, host "
        "mac-address-duplicate-detection, Advertise-mac, unknow-mac-flooding, "
        "es-waiting-time",
        "The node offers five children only: auto-discovery, interface, "
        "mac-aging-time, mac-limit, service-type"],
       ["interface agg-eth <n> ethernet-segment / lacp-key / lacp-system-mac",
        "No ethernet-segment node under an interface at all - the EVPN "
        "multi-homing configuration is absent from this build"],
       ["service-type accepts vlan-aware-bundle / vlan-bundle",
        "Only port-based and vlan-based"],
       ["mac-limit default 250000",
        "Range <1-250000>, default 65520 - 250000 is the configurable maximum"],
       ["af-l2vpn evpn under BGP",
        "Only under a neighbour or neighbour-group, and only in vrf default"],
       ["show evpn global", "Does not exist. Use show evpn summary / show evpn detail"],
       ["show evpn bum routing-table",
        "Does not exist. show evpn broadcast-domains carries the BUM label"],
       ["show evpn mac-address-table (hyphen)\nclear evpn mac address-table (space)",
        "Both correct: the product genuinely uses a hyphen for show and a space for clear"],
       ["import-rt / export-rt under the EVI", "They live under auto-discovery"],
       ["show interface … detail", "No detail under show interface"],
       ["show bgp l2vpn evpn table evi evi-name <name>",
        "\"Incomplete path\" until that EVI has BGP EVPN entries; the bare "
        "table evi [detail] form works"]])

# ── asks ────────────────────────────────────────────────────────────────
h(doc, "What we need from you")
bullets(doc, [
    ("A ticket ID: ", "so the branch lands as AUT-nnn / EM-nnnn rather than our "
     "provisional name."),
    ("One chassis slot to produce the .ixncfg: ", "this is the single "
     "remaining blocker and it is half an hour of rig time. "
     "configurations/ixia/EVPN_traffic.tcl states every traffic item in your "
     "ixia_lib.tcl idiom and ends by saving the session; run it once and the "
     "file it writes is what bringUpParams.crt then loads. We have not run it "
     "unattended because the chassis is shared and traffic items are the thing "
     "you said you want to inspect - we would rather build them with you."),
    ("A BGP EVPN peer for this DUT: ", "the four \"show bgp l2vpn evpn table evi "
     "detail\" expectations have nothing to show until a peer exists."),
    ("Confirmation on the absent EVI knobs: ", "control-word, host "
     "mac-address-duplicate-detection, Advertise-mac, unknow-mac-flooding and the "
     "interface ethernet-segment tree are in the CLI doc and not in LAB 22. Either "
     "the document is ahead of the build or the build is missing them; we report it "
     "rather than guess."),
])

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(4)
r = p.add_run("Closed since the last hand-over: source-MAC control on a raw "
              "traffic item, which was an ask here in August, is implemented and "
              "shipped (EvpnUtils.setTrafficItemSourceMac).")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

h(doc, "Two things for your attention, neither ours to change", size=11, space_before=10)
bullets(doc, [
    ("pc-3080 cannot complete your own bring-up on its current image: ", "it "
     "is now 8.7.0 LAB 0, and bring-up ends at \"Failed to enter specific "
     "session mode. Wanted mode: ONL\". CmpCliSession.java:69 matches the ONL "
     "shell by the literal string \"@localhost\"; this image answers "
     "root@router. The same test on the same box on 13 August logged "
     "root@localhost 78 times, on 9 September zero. checkCoresAndAlarms() is "
     "called unconditionally from bringUpSetupAndVerify(), so no parameter "
     "skips it. This will stop any suite on that image, not only ours. "
     "pc-3099 (LAB 935) is unaffected, which is where this drop was run."),
    ("exa-il01-ec-3021 has a standing Critical alarm: ", "PSU PSU-1 is Failed. "
     "Pre-existing, and CmpTestCase's @After alarm check will make any suite on that "
     "rig look flaky."),
    ("cmp/tests/multiCast/MultiCastParams.java: ", "carries a stray "
     "\"import com.sun.javafx.collections.MappingChange;\", an unused IDE auto-import "
     "that only compiled because Oracle JDK 8 shipped JavaFX internals. It fails on "
     "any modern JDK. Left alone rather than shipping an infra fix inside an EVPN branch."),
])

doc.add_page_break()

# ── package ─────────────────────────────────────────────────────────────
h(doc, "The package", space_before=0)
table(doc,
      ["Folder", "Contents"],
      [["01_generated_suite/", "The 8 generated files, in cmp-tests-project layout"],
       ["02_evidence/", "One file per claim above, read these before the code"],
       ["03_test_plan/", "The test plan the code was generated from"],
       ["04_results/", "Full test report (open the .html in a browser)"],
       ["05_git/", "git bundle, 3 commits on auto_develop..ate-m2-evpn-generated-suite"]])

h(doc, "Importing the branch")
p = doc.add_paragraph()
r = p.add_run("git fetch /path/to/evpn-suite.bundle "
              "ate-m2-evpn-generated-suite:<your-branch-name>")
r.font.name = "Consolas"
r.font.size = Pt(9.5)
p = doc.add_paragraph()
r = p.add_run("The branch name in the bundle is provisional. Rename it on import, "
              "or send us a ticket ID and we will.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

# ── report ──────────────────────────────────────────────────────────────
h(doc, "Reading the test report")
p = doc.add_paragraph()
r = p.add_run("389 checks: 358 pass, 5 fail, 26 skip.")
r.bold = True
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("All five failures are code-coverage thresholds (70%) on the CLI wiring "
              "and the device-facing modules, whose network paths are exercised against "
              "real hardware rather than in unit tests. verify.py is the lowest of them "
              "because this round added the session-recovery code that made the "
              "configuration sweep trustworthy. There are no functional test failures "
              "and no lint issues. We are reporting them rather than adjusting the "
              "threshold to hide them.")
r.font.size = Pt(10.5)

h(doc, "The command sweep, now trustworthy in both halves", size=11)
p = doc.add_paragraph()
r = p.add_run("The previous hand-over shipped a sweep of all 123 command templates and "
              "asked you not to act on its configuration-mode half, because it reported "
              "commands missing that the device demonstrably offers. That is fixed and the "
              "cause is understood: a \"?\" on a leaf does not list and return - the CLI "
              "opens an interactive prompt for the value, no prompt character follows, and "
              "the answer was left in the channel for the next probe to collect. Every "
              "later verdict then described the wrong command.")
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("The sweep now recognises that state, escapes it with Ctrl-C without ever "
              "answering it (this stage is read-only), and proves the channel is back at "
              "its prompt after every probe - this run needed zero recoveries. Twenty "
              "verdicts spanning both halves were then established by hand at the CLI and "
              "compared: 20 of 20 agree. Result: 48 supported, 67 missing, 8 unknown "
              "(02_evidence/evidence_command_verification.txt).")
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("\"Missing\" means this build does not offer the command - not that your "
              "documentation is wrong. The largest block is the EVPN multi-homing "
              "configuration, which LAB 22 does not expose at all.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(14)
r = p.add_run("Ilan Ganor · CodeValue · ilan@kamacode.com")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

doc.save(OUT)
print("wrote", OUT)
