"""
 Simple DHCP Server
"""
import logging

import binascii

from ryu.ofproto import ofproto_v1_3
from ryu.base import app_manager
from ryu.lib.packet import dhcp, udp
from ryu.lib.packet import ipv4
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.lib.packet import packet

class DHCPServer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
  
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        pkt = packet.Packet(msg.data)
        udpPacket = pkt.get_protocol(udp.udp)

        # check if DHCP Pacet
        if udpPacket:
            dhcpPacket = dhcp.dhcp.parser(pkt.protocols[-1])[0]
            self.logger.info("pkt...%s", dhcpPacket)
            
            if dhcpPacket.op == dhcp.DHCP_DISCOVER:
                self.logger.info("Discover message.") 
                self.handle_dhcp_request(dhcpPacket) 
           
    def handle_dhcp_discover(self, dhcpPacket):
        pass

    def handle_dhcp_offer(self):
        pass
