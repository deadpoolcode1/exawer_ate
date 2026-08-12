#!/usr/bin/env python3
"""Build the client-facing milestone hand-over .docx.

Separate from `build_docs_docx.py`, which converts our internal markdown docs
via pandoc. This one is written directly with python-docx because a hand-over
is a different artifact: two pages, three tables, and every claim in it has a
matching file in the evidence folder.

Regenerate after changing any of the numbers it quotes — they are deliberately
inline rather than computed, so that a stale figure is a visible edit in the
diff rather than something the script silently recalculates from a run that no
longer matches what was shipped.

    python scripts/build_handover_docx.py

Output path is the milestone package on the Desktop; change OUT for a new
milestone.
"""
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

OUT = "/home/ilan/Desktop/Exaware_M2_handover_2026-08-12/M2_Handover.docx"
#: Keep in step with deliverables/M2/ — every claim below has an evidence file.
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
r = t.add_run("Milestone 2 — Hand-over")
r.bold = True
r.font.size = Pt(20)
r.font.color.rgb = ACCENT

s = doc.add_paragraph()
s.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = s.add_run("Dirty Queue & Code Generation · SOW PQ4476E\n"
              "CodeValue → Exaware · 12 August 2026")
r.font.size = Pt(10)
r.font.color.rgb = MUTED

# ── acceptance ──────────────────────────────────────────────────────────
h(doc, "M2 deliverables — all four met", space_before=14)
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
r = p.add_run("SUT pc-3021 / exa-il01-ec-3021, software 8.7.0 LAB 22.")
r.font.size = Pt(10)
bullets(doc, [
    ("Compiles against your framework — ",
     "953 sources → 1454 classes, zero errors; the generated files pass "
     "javac --release 8 -Werror -Xlint:all with zero warnings."),
    ("bringUpParams.crt passes your own validator — ",
     "TemplateManager.validateAgainstTemplate returns true (bringUpParameters_C0_002)."),
    ("The .cfg block shape is confirmed — ",
     "an EVI was configured and show configuration l2-services printed exactly "
     "the hierarchy the generator emits."),
    ("7 of 10 expected-output tables captured from the live device — ",
     "0 commands unsupported; the remaining 3 need traffic or a BGP peer before "
     "there is anything to capture."),
    ("TC01 executed under JUnit + JSystem — ",
     "reached template validation, device topology, terminal-server login and "
     "ONL-level setup before needing lab-workspace files that live on your runner."),
])

# ── doc corrections ─────────────────────────────────────────────────────
h(doc, "Corrections your EVPN CLI documentation may want")
p = doc.add_paragraph()
r = p.add_run("Found by running against LAB 22, not by reading.")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED
table(doc,
      ["EVPN CLI 1.00 says", "LAB 22 does"],
      [["show evpn global", "Does not exist — show evpn summary / show evpn detail"],
       ["show evpn bum routing-table",
        "Does not exist — show evpn broadcast-domains carries the BUM label"],
       ["show evpn mac-address-table (hyphen)\nclear evpn mac address-table (space)",
        "Both correct — the product genuinely uses a hyphen for show and a space for clear"],
       ["import-rt / export-rt under the EVI", "They live under auto-discovery"],
       ["show interface … detail", "No detail under show interface"],
       ["show bgp l2vpn evpn table evi evi-name <name>",
        "\"Incomplete path\" until that EVI has BGP EVPN entries; the bare "
        "table evi [detail] form works"]])

# ── asks ────────────────────────────────────────────────────────────────
h(doc, "What we need from you")
bullets(doc, [
    ("A ticket ID — ", "so the branch lands as AUT-nnn / EM-nnnn rather than our "
     "provisional name."),
    ("Source-MAC control on the IXIA — ", "we build the three traffic items in code "
     "over TCL, so no .ixncfg is needed for traffic itself. But ixia_lib.tcl has "
     "editTrafficRawDestMacAddr and no source equivalent, and EVPN learns from source "
     "MACs — so the local MAC-move case (AC2 and AC3 emitting the same source MAC) "
     "cannot be expressed. A src-MAC proc, or an .ixncfg with the three items, "
     "unblocks TC02 and TC03."),
    ("Lab-workspace files — ", "site config, ONL images and terminal-server plumbing, "
     "for a complete bring-up."),
])

h(doc, "Two things for your attention, neither ours to change", size=11, space_before=10)
bullets(doc, [
    ("exa-il01-ec-3021 has a standing Critical alarm — ", "PSU PSU-1 is Failed. "
     "Pre-existing, and CmpTestCase's @After alarm check will make any suite on this "
     "rig look flaky."),
    ("cmp/tests/multiCast/MultiCastParams.java — ", "carries a stray "
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
       ["02_evidence/", "One file per claim above — read these before the code"],
       ["03_test_plan/", "The test plan the code was generated from"],
       ["04_results/", "Full test report (open the .html in a browser)"],
       ["05_git/", "git bundle — 3 commits on auto_develop..ate-m2-evpn-generated-suite"]])

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
r = p.add_run("363 checks — 332 pass, 5 fail, 26 skip.")
r.bold = True
r.font.size = Pt(10.5)
p = doc.add_paragraph()
r = p.add_run("All five failures are code-coverage thresholds (70%) on modules added "
              "late in this milestone: the CLI wiring and the three device-facing "
              "modules, whose network paths are exercised against real hardware rather "
              "than in unit tests. There are no functional test failures and no lint "
              "issues. We are reporting them rather than adjusting the threshold to "
              "hide them.")
r.font.size = Pt(10.5)

h(doc, "One limit we want to be explicit about", size=11)
p = doc.add_paragraph()
r = p.add_run("A mechanical sweep of all 123 command templates is included "
              "(02_evidence/evidence_command_verification.txt). Its show/clear half is "
              "sound and hand-checked — that is where the documentation corrections "
              "above come from. Its configuration-mode half is not yet trustworthy: it "
              "reports commands missing that the device demonstrably offers, and it is "
              "marked as such. Please do not act on the configuration verdicts.")
r.font.size = Pt(10.5)

p = doc.add_paragraph()
p.paragraph_format.space_before = Pt(14)
r = p.add_run("Ilan Ganor · CodeValue · ilan@kamacode.com")
r.font.size = Pt(9.5)
r.font.color.rgb = MUTED

doc.save(OUT)
print("wrote", OUT)
