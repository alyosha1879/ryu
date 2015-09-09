"""
 Simple DHCP Server
"""
import logging

from ryu.base import app_manager
from ryu.lib.packet import dhcp
from ryu.lib.packet import ipv4
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.lib.packet import packet

class DHCPServer(app_manager.RyuApp):
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        pkt = packet.Packet(msg.data)
        #self.logger.info("pkt...%s", pkt)
        dhcpPacket = pkt.get_protocol(dhcp.dhcp)
        self.logger.info("dhcp...%s", dhcpPacket)

        if dhcpPacket:
           pass

    def handle_dhcp_request(self):
        pass

    def handle_dhcp_offer(self):
        pass

    def handle_dhcp_ack(self):
        pass
