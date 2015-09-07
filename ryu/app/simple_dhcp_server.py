"""
 Simple DHCP Server
"""

class DHCPServer():
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        pkt = packet.Packet(msg.data)

        udpPacket = pkt.get_protocol(udp.udp)
 
        if udpPacket:
           pass

    def handle_dhcp_request(self):

    def handle_dhcp_offer(self):

    def handle_dhcp_ack(self):  
