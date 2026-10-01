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
#: From the 04_results report this package ships. Inline on purpose, see above.
UNIT_TESTS = "472 checks: 439 pass, 7 fail, 26 skip. All 345 unit tests pass."
UNIT_TESTS_NOTE = ("All seven failures are code-coverage thresholds (70%) on the CLI "
                   "wiring, the device-facing modules and two M1 plan-diff modules. "
                   "Their paths run against real hardware or by hand, not in unit "
                   "tests. No functional failures, no lint issues. We report them "
                   "rather than lower the threshold.")
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
              "CodeValue → Exaware · 1 October 2026")
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
r = p.add_run("SUT pc-3080 / exa-il01-uf-3080, DUT_SW_VERSION 8.7.0_116, "
              "run 1 October 2026. Lab profile 3ac-core. One reboot per test.")
r.font.size = Pt(10)
table(doc,
      ["Suite", "Result", "Checks passed"],
      [["TC01 VLAN-based bring-up", "OK, every step", "79"],
       ["TC02 Type-2 MAC/IP + local move", "OK, every step", "162"],
       ["TC03 Type-3 IMET + flooding + aging", "OK, every step", "136"]])
p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(6)
r = p.add_run("No failures, no warnings. One report for all three: "
              "06_automation_report/index.html.")
r.font.size = Pt(10.5)
bullets(doc, [
    ("Underlay: ",
     "OSPF Full, LDP Operational, BGP loopback to loopback (29.30.30.30 to "
     "29.31.31.31) with the next hop over an LDP LSP. All three checked on the "
     "DUT in every test."),
    ("EVPN negotiated with the tester: ",
     "\"L2VPN EVPN: advertised and received\". No license needed."),
    ("Advertisement: ",
     "asserted on the routes the DUT sent to the tester (show bgp l2vpn evpn "
     "neighbors advertised-routes 29.31.31.31 detail), including MAC Mobility "
     "SeqNum."),
    ("Traffic: ",
     "known unicast per AC. Floods while the MAC is unknown, goes out the right "
     "AC once learned, follows a local move, floods again after aging. Egress "
     "is read per AC from the DUT sub-interface counters."),
    ("The service in one commit: ",
     "service-type, two route targets and three ACs (x-eth0/0/18.1001, "
     "x-eth0/0/26.1002, x-eth0/0/26.1003)."),
    ("Bring-up: ",
     "protocols start in the .crt do-before, the ping list is populated. "
     "TC02 and TC03 start from EVPN_Service.cfg."),
    ("Compiles against your framework: ",
     "javac --release 8 -Werror -Xlint:all, zero warnings. bringUpParams.crt "
     "passes TemplateManager.validateAgainstTemplate."),
    ("Nothing fakes a pass: ",
     "33 of 33 verification steps can fail; none only warn. The package build "
     "refuses a report that is older than the code it ships with."),
    ("Reviewed before it is generated: ",
     "every step is checked against the defects your reviewers found (e.g. "
     "aging asserted on a MAC never learnt). That check added TC03 step 10: "
     "the Type-2 is shown advertised before it is shown withdrawn."),
])

h(doc, "What is NOT proven, and why", size=11, space_before=10)
bullets(doc, [
    ("Receiving EVPN routes from a peer: ",
     "the tester negotiates EVPN but advertises no EVPN routes. Emulating them "
     "needs a BGP EVPN license on chassis 10.1.70.108 (ERROR-1005). The current "
     "TCs do not need it."),
])

h(doc, "Things for your attention, not ours to change", size=11, space_before=10)
bullets(doc, [
    ("pc-3080 serial console: ",
     "about half the bring-ups time out on the serial console before step 1 "
     "(a stray router# prompt, or the switch to ONL mode in "
     "checkCoresAndAlarms). It is in the framework's bring-up, before the test "
     "runs. We rerun those; scripts/lab/run_with_retry.sh retries bring-up "
     "deaths only, never a failed step."),
    ("Deleting an EVI cores bgpd and rpki_mo: ",
     "seen on 8.7.0 LAB 938. Your bring-up deletes the EVI when it loads the "
     "base config, so we run one reboot per test. See "
     "evidence_bgpd_crash_on_evi_delete.txt."),
    ("exa-il01-ec-3021 has a standing Critical alarm: ", "PSU PSU-1 is Failed. "
     "CmpTestCase's @After alarm check will make any suite on that rig look "
     "flaky."),
    ("cmp/tests/multiCast/MultiCastParams.java: ", "carries a stray "
     "\"import com.sun.javafx.collections.MappingChange;\" that fails on any "
     "modern JDK. Left alone rather than shipping an infra fix inside an EVPN "
     "branch."),
])

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
        "Only under a neighbor or neighbor-group, and only in vrf default"],
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
    ("A ticket ID: ", "so the branch lands as AUT-nnn / EM-nnnn. 05_git stays "
     "empty until then."),
    ("A fix for the EVI-delete core: ", "until then each test needs its own "
     "reboot."),
    ("Confirmation on the absent EVI knobs: ", "control-word, host "
     "mac-address-duplicate-detection, Advertise-mac, unknow-mac-flooding and the "
     "interface ethernet-segment tree are in the CLI doc and not in the build. "
     "Either the document is ahead of the build or the build is missing them."),
])

doc.add_page_break()

# ── package ─────────────────────────────────────────────────────────────
h(doc, "The package", space_before=0)
table(doc,
      ["Folder", "Contents"],
      [["01_generated_suite/", "The generated files, in cmp-tests-project layout"],
       ["06_automation_report/", "Open index.html: every step, the command "
        "issued, Expected vs Output and the verdict"],
       ["02_evidence/", "One file per claim above"],
       ["03_test_plan/", "The test plan, and TC_sources.md: what was fed to "
        "the engine for each TC"],
       ["04_results/", "Unit test report (open the .html in a browser)"],
       ["05_git/", "Empty until we have a ticket ID; WHY_THIS_IS_EMPTY.md"]])

# ── report ──────────────────────────────────────────────────────────────
h(doc, "Reading the unit test report")
p = doc.add_paragraph()
r = p.add_run(UNIT_TESTS)
r.bold = True
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run(UNIT_TESTS_NOTE)
r.font.size = Pt(10.5)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(14)
r = p.add_run("Ilan Ganor · CodeValue · ilan@kamacode.com")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

doc.save(OUT)
print("wrote", OUT)
