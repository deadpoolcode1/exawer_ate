# Build an emulated BGP EVPN peer on IXIA, facing the DUT's core link.
#
# WHY THIS FILE EXISTS
#
# The EVPN suite long recorded "a BGP EVPN peer for the DUT" as blocked on
# Exaware, and the rig as having no peer available. Both were wrong. IXIA is
# the peer - it is used as client traffic endpoints AND as the remote router
# (Ilan, 2026-08-13). Nothing in the generator modelled the second job, so
# every vport was wired as an attachment circuit and there was no core side.
#
# WHAT IS VERIFIED, AND WHAT IS NOT
#
# Every object below was created and committed against chassis 10.1.70.108 on
# 2026-08-13, and each value here was read back off the chassis rather than
# assumed. The one thing that does NOT work is starting it:
#
#     ixNet exec start /vport:1/protocols/bgp
#     ERROR-1005-Cannot start protocol due a missing license:
#     There is no license available for BGP EVPN.
#
# That is a licensing item on the IXIA chassis, not a code or config problem.
# Proof it is specifically the EVPN feature and not BGP as a whole: removing
# the `ethernetSegments` object below and starting the same neighbour with
# plain ipv4-unicast gives `BGP-RUNNING=started`, and the DUT then reports
# `BGP state: Established`. So the whole path is correct and in place; only
# the EVPN address family cannot be brought up until the licence is added.
#
# Run it from the IXIA app server (tate, 10.1.70.200):  tclsh ixia_evpn_peer.tcl
#
# The addressing matches what `ate codegen --lab 2ac-core` emits into
# EVPN_Base.cfg: DUT core 29.60.0.1/24, loopback 29.30.30.30, AS 3029,
# import/export RT 65000:1.

source /auto/software/tools/Ixia/IxOS-6.30.701.16_veryNew/lib/IxTclNetwork/pkgIndex.tcl
package require IxTclNetwork

proc P {m} { puts $m; flush stdout }

# NOTE: the SUT pins the *client* TCL library at 6.30, which is where the
# "this IxNetwork is too old for EVPN" reading came from. The API server
# actually answers 9.00.1915.16, and it carries the full EVPN object tree.
if {[catch {ixNet connect 10.1.90.80 -version 6.0} err]} {
    P "CONNECT-FAIL: $err"; exit 1
}
P "CONNECTED [ixNet getVersion]"

ixNet exec newConfig
after 4000
set root [ixNet getRoot]

# --- chassis -------------------------------------------------------------
set ch [ixNet add $root/availableHardware chassis]
ixNet setAtt $ch -hostname 10.1.70.108
ixNet commit
set ch [lindex [ixNet remapIds $ch] 0]

# --- the core vport: data1 index 0, i.e. DUT x-eth 0/0/8 <-> card 5 port 1.
# This is the port the DUT's core interface faces. The other two vports stay
# attachment circuits and must NOT get an L3 interface: a raw traffic item's
# endpoint is only accepted in the /vport:N/protocols form when the vport has
# exactly one interface with a VLAN, and a second interface breaks it
# (chassis answers ERROR-6301).
set vp [ixNet add $root vport]
ixNet commit
set vp [lindex [ixNet remapIds $vp] 0]
ixNet setAtt $vp -connectedTo $ch/card:5/port:1
ixNet commit
P "VPORT=$vp"

# --- routed interface facing the DUT ------------------------------------
set intf [ixNet add $vp interface]
ixNet setAtt $intf -enabled true -description evpn-core
ixNet commit
set intf [lindex [ixNet remapIds $intf] 0]
set v4 [ixNet add $intf ipv4]
ixNet setAtt $v4 -ip 29.60.0.2 -gateway 29.60.0.1 -maskWidth 24
ixNet commit
P "INTF=$intf"

# --- BGP, EVPN address family -------------------------------------------
set bgp $vp/protocols/bgp
ixNet setAtt $bgp -enabled true
ixNet commit
# Read back rather than assume: the chassis reports AFI 25 / SAFI 70, which
# is L2VPN / EVPN.
P "eVpnAfi=[ixNet getAtt $bgp -eVpnAfi] eVpnSafi=[ixNet getAtt $bgp -eVpnSafi]"

set nr [ixNet add $bgp neighborRange]
ixNet setAtt $nr -enabled true -evpn true -type internal \
    -dutIpAddress 29.60.0.1 -localIpAddress 29.60.0.2 \
    -localAsNumber 3029 -interfaces $intf -enableBgpId true -bgpId 29.60.0.2
ixNet commit
set nr [lindex [ixNet remapIds $nr] 0]
P "NEIGHBOR evpn=[ixNet getAtt $nr -evpn] dut=[ixNet getAtt $nr -dutIpAddress]"

# --- ethernet segment -> EVI -> broadcast domain -> customer MACs --------
# The route targets match the EVI the DUT config commits (65000:1), so the
# emulated PE's Type-2/Type-3 routes are importable by evi-1.
set es [ixNet add $nr ethernetSegments]
ixNet setAtt $es -enabled true -typeOfEthernetVpn evpn
ixNet commit
set es [lindex [ixNet remapIds $es] 0]

set evi [ixNet add $es evi]
ixNet setAtt $evi -enabled true -rdEvi 1 -rdIpAddress 29.60.0.2 \
    -importTargetList [list [list as 65000 0.0.0.0 1]] \
    -exportTargetList [list [list as 65000 0.0.0.0 1]]
ixNet commit
set evi [lindex [ixNet remapIds $evi] 0]

set bd [ixNet add $evi broadcastDomains]
ixNet setAtt $bd -enabled true -ethernetTagId 0
ixNet commit
set bd [lindex [ixNet remapIds $bd] 0]

set mr [ixNet add $bd cMacRange]
ixNet setAtt $mr -enabled true -startCmacPrefix "00:00:aa:00:00:01" \
    -noOfCmacs 5 -cmacPrefixLength 48
ixNet commit
set mr [lindex [ixNet remapIds $mr] 0]
P "MACRANGE start=[ixNet getAtt $mr -startCmacPrefix] count=[ixNet getAtt $mr -noOfCmacs]"

# --- take the port and start --------------------------------------------
if {[catch {ixNet exec connectPorts $vp} e]} { P "connectPorts: $e" }
after 15000
P "PORT state=[ixNet getAtt $vp -state] connected=[ixNet getAtt $vp -isConnected]"

# This is the step that needs the licence. Everything above commits cleanly
# without one.
if {[catch {ixNet exec start $bgp} e]} {
    P "START FAILED (expected until the BGP EVPN licence is added): $e"
} else {
    P "START OK"
}
after 25000
P "BGP-RUNNING=[ixNet getAtt $bgp -runningState]"
