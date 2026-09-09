import sys, time
sys.path.insert(0, "/tmp")
from dut import Dut
d = Dut("10.3.99.1")
print(d.run("configure", limit=60))
print(d.run("no l2-services evpn evi-1", limit=60))
print(d.run("commit", limit=180))
print(d.run("end", limit=60))
time.sleep(10)
print("CONFIG after delete:", d.run("show configuration l2-services", limit=60)[:60])
d.close()
