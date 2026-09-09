# Lab helpers

Small scripts used to drive pc-3099 and the IXIA chassis by hand. They are
here so the recipe survives the session, not because the pipeline needs them.

| Script | What it does |
|---|---|
| `cycle.sh` | Reboot the DUT to a clean state, settle it, zero the syslog, set the ONL hostname, verify it, then run one test. ~14 min. Runs ON the dev box. |
| `clean_reboot.py` | Remove the EVI and commit, before a reboot. |
| `sethost.py` | Set the ONL hostname to `localhost`, which Exaware's bring-up matches literally. |
| `syslog.py` | Zero `/var/log/syslog`, so their `less`-based bring-up check does not page and time out. |
| `dut.py` | Minimal Exaware CLI driver over SSH (prompt handling, commit spinner). |
| `tate.py` | Run a command or push a file to tate, the IXIA application host. |

`cycle.sh`, `clean_reboot.py`, `sethost.py` and `syslog.py` live on the dev
box under `/var/tmp/ate-run/` and are invoked there:

    ssh axawear '/var/tmp/ate-run/cycle.sh TC02_EvpnType2MacIpAdvertisement'

`dut.py` is copied to `/tmp/dut.py` on the dev box; `tate.py` runs locally.

Why any of this is needed is in `deliverables/M2/RESUME_2026-09-09.md`.
