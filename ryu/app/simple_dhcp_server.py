"""
 Simple DHCP Server
"""
import logging

from ryu.ofproto import ofproto_v1_3
from ryu.base import app_manager
from ryu.lib.packet import dhcp, udp, ipv4, ethernet
from ryu.controller.handler import set_ev_cls
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER
from ryu.lib.packet import packet
from ryu.lib import addrconv

class SimpleDHCPServer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
 
    def __init__(self, *args, **kwargs):
        super(SimpleDHCPServer, self).__init__(*args, **kwargs)
        self.hw_addr = "08:00:27:b8:0f:8d"
        self.ip_addr = "192.168.1.1" 


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        udpPacket = pkt.get_protocol(udp.udp)

        # check if DHCP Pacet
        if udpPacket and udpPacket.src_port == 68:
            dhcpPacket = dhcp.dhcp.parser(pkt.protocols[-1])[0]
            #self.logger.info("pkt...%s", dhcpPacket)
   
            msgType = dhcpPacket.options.option_list[0].value
        
            if msgType == '\x01':
                self.logger.info("Discover message.") 
                self.handle_dhcp_discover(dhcpPacket, datapath, in_port) 

            if msgType == '\x03':
                self.logger.info("Request message.")
                self.handle_dhcp_request(dhcpPacket, datapath, in_port) 

           
    def handle_dhcp_discover(self, dhcp_pkt, datapath, port):
 
        # send dhcp_offer message.
        #msgOption = dhcp.option(tag=dhcp.DHCP_MESSAGE_TYPE_OPT, value='\x02')
        msgOption = dhcp.option(tag=53, value='\x02')

        options = dhcp.options(option_list = [msgOption])

        heln = len(addrconv.mac.text_to_bin(dhcp_pkt.chaddr))
 
        dhcp_pkt = dhcp.dhcp(hlen=heln, op=dhcp.DHCP_BOOT_REPLY, chaddr=dhcp_pkt.chaddr, yiaddr=dhcp_pkt.yiaddr, giaddr=dhcp_pkt.giaddr, xid=dhcp_pkt.xid, options=options)
        self._send_dhcp_packet(datapath, dhcp_pkt, port)


    def handle_dhcp_request(self, dhcp_pkt, datapath, port):

        # send dhcp_ack message.
        subnetOption = dhcp.option(tag=dhcp.DHCP_SUBNET_MASK_OPT, value='\xFF\xFF\xFF\x00')
        gwOption = dhcp.option(tag=dhcp.DHCP_GATEWAY_ADDR_OPT, value='\x0B\x0B\x0B\x01')
        dnsOption = dhcp.option(tag=dhcp.DHCP_DNS_SERVER_ADDR_OPT, value='\x0B\x0B\x0B\x01')
        timeOption = dhcp.option(tag=dhcp.DHCP_IP_ADDR_LEASE_TIME_OPT, value='\xFF\xFF\xFF\xFF')     
        msgOption = dhcp.option(tag=dhcp.DHCP_MESSAGE_TYPE_OPT,value='\x05')
        idOption = dhcp.option(tag=dhcp.DHCP_SERVER_IDENTIFIER_OPT, value='\xc0\xa8\x01\x01')

        options = dhcp.options(option_list = [msgOption, idOption, timeOption, subnetOption, gwOption])
        heln = len(addrconv.mac.text_to_bin(dhcp_pkt.chaddr))

        dhcp_pkt = dhcp.dhcp(op=dhcp.DHCP_BOOT_REPLY, hlen=hlen, chaddr=dhcp_pkt.chaddr, yiaddr="192.168.1.100", giaddr=dhcp_pkt.giaddr, xid=dhcp_pkt.xid, options=options)
        self._send_dhcp_packet(datapath, dhcp_pkt, port)


    def _send_dhcp_packet(self, datapath, dhcp_pkt, port):

        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(src=self.hw_addr, dst=dhcp_pkt.chaddr))
        pkt.add_protocol(ipv4.ipv4(src=self.ip_addr, dst="255.255.255.255", proto=17))
        pkt.add_protocol(udp.udp(src_port=67, dst_port=68))
        pkt.add_protocol(dhcp_pkt)

        self._send_packet(datapath, pkt, port)

    def _send_packet(self, datapath, pkt, port):

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
