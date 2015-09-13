"""
 Simple DHCP Server
"""
import logging

from ryu.ofproto import ofproto_v1_3
from ryu.base import app_manager
from ryu.lib.packet import dhcp, udp
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
                self.handle_dhcp_discover(dhcpPacket, msg, datapath) 
           
    def handle_dhcp_discover(self, dhcpPacket, msg, datapath):
 
        #msg.buffer = dhcpPacket
        datapath.send_msg(msg)


    def handle_dhcp_offer(self):
        pass

    def handle_dhcp_ack(self):
        pass

    def _send_packet(self, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        pkt.serialize()
        self.logger.info("packet-out %s" % (pkt,))
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)
