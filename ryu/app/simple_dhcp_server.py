"""
 Simple DHCP Server
"""
import logging

from ryu.base import app_manager
from ryu.lib.packet import dchp

class DHCPServer():
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        pkt = packet.Packet(msg.data)
        dhcpPacket = pkt.get_protocol(dhcp.dhcp)
        self.logger.info("dchp...%s", dhcpPacket)
 
        if dhcpPacket:
           pass

    def handle_dhcp_request(self):

    def handle_dhcp_offer(self):

    def handle_dhcp_ack(self):  
