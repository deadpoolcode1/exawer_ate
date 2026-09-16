# The report Exaware rejected, kept as the gate's fixture

This is the `06_automation_report` we shipped on 2026-09-10 and Oded Engel
reviewed on 2026-09-15. It is kept unchanged, and it is **not** the report any
package ships. `../automation_report/` is.

It is here because `scripts/verify_automation_report.py` is tested against it:
`tests/test_codegen.py::test_the_report_gate_refuses_the_package_the_client_rejected`
requires the gate to reproduce, on its own, every finding the client made -
the missing suites, the 65 unlisted test folders, each undeclared warning, and
the `Final test status is : Warning` verdict that contradicted our mail's
"0 failures".

A gate with no failing fixture is a gate nobody can show works.
