import sys
sys.path.append('..')

from src.sim import Sim
from src.connection import Connection
from src.tcppacket import TCPPacket
from src.buffer import SendBuffer,ReceiveBuffer

class TCP(Connection):
    ''' A TCP connection between two hosts.'''
    def __init__(self,transport,source_address,source_port,
                 destination_address,destination_port,app=None,window=1000):
        Connection.__init__(self,transport,source_address,source_port,
                            destination_address,destination_port,app)

        ### Sender functionality

        # send window; represents the total number of bytes that may
        # be outstanding at one time
        self.window = window
        # send buffer
        self.send_buffer = SendBuffer()
        # maximum segment size, in bytes
        self.mss = 1000
        # largest sequence number that has been ACKed so far; represents
        # the next sequence number the client expects to receive
        self.sequence = 0
        # retransmission timer
        self.timer = None
        # timeout duration in seconds
        self.timeout = 1

        ### Receiver functionality

        # receive buffer
        self.receive_buffer = ReceiveBuffer()
        # ack number to send; represents the largest in-order sequence
        # number not yet received
        self.ack = 0

    def trace(self,message):
        ''' Print debugging messages. '''
        Sim.trace("TCP",message)

    def receive_packet(self,packet):
        ''' Receive a packet from the network layer. '''
        if packet.ack_number > 0:
            # handle ACK
            self.handle_ack(packet)
        if packet.length > 0:
            # handle data
            self.handle_data(packet)

    ''' Sender '''

    def send(self,data):
        ''' Send data on the connection. Called by the application. This
            code currently sends all data immediately. '''
        self.send_buffer.put(data)
        print "Data added to buffer."
        self.send_next_packet_if_possible()

    def send_next_packet_if_possible(self):
        while self.send_buffer.available() > 0 and self.send_buffer.outstanding() < self.window:
            self.restart_timer()

            new_data, new_sequence = self.send_buffer.get(self.mss)
            self.send_packet(new_data, new_sequence)

            message = ("Window not full (") + str(self.send_buffer.outstanding()) + (") sent packet: " + str(new_sequence))
            print message


    def send_packet(self,data,sequence):
        packet = TCPPacket(source_address=self.source_address,
                           source_port=self.source_port,
                           destination_address=self.destination_address,
                           destination_port=self.destination_port,
                           body=data,
                           sequence=sequence,ack_number=self.ack)

        # send the packet
        self.trace("%s (%d) sending TCP segment to %d for %d" % (self.node.hostname,self.source_address,self.destination_address,packet.sequence))
        self.transport.send_packet(packet)

    def handle_ack(self,packet):
        self.send_buffer.slide(packet.ack_number)
        self.send_next_packet_if_possible()

        if self.send_buffer.available() == 0:
            self.cancel_timer()

    def retransmit(self,event):
        ''' Retransmit data. '''
        self.restart_timer()
        resend_data, resend_sequence = self.send_buffer.resend(self.mss)
        self.send_packet(resend_data, resend_sequence)
        self.trace("%s (%d) retransmission timer fired" % (self.node.hostname,self.source_address))

    def restart_timer(self):
        self.cancel_timer()
        self.start_timer()

    def start_timer(self):
        if self.timer == None:
            self.timer = Sim.scheduler.add(delay=self.timeout, event='retransmit', handler=self.retransmit)

    def cancel_timer(self):
        ''' Cancel the timer. '''
        if not self.timer:
            return
        Sim.scheduler.cancel(self.timer)
        self.timer = None

    ''' Receiver '''

    def handle_data(self,packet):
        ''' Handle incoming data. This code currently gives all data to
            the application, regardless of whether it is in order, and sends
            an ACK.'''
        self.trace("%s (%d) received TCP segment from %d; Seq: %d, Ack: %d" % (self.node.hostname,packet.destination_address,packet.source_address,packet.sequence,packet.ack_number))
        self.receive_buffer.put(packet.body, packet.sequence)

        if self.ack == packet.sequence:
            self.ack += packet.length
            print "Sent ACK: " + str(self.ack)

        # SEND DATA TO APPLICATION
        data, last_sequence_number = self.receive_buffer.get()
        self.app.receive_data(data)
        self.send_ack()

    def send_ack(self):
        ''' Send an ack. '''
        packet = TCPPacket(source_address=self.source_address,
                           source_port=self.source_port,
                           destination_address=self.destination_address,
                           destination_port=self.destination_port,
                           sequence=self.sequence,ack_number=self.ack)
        # send the packet
        self.trace("%s (%d) sending TCP ACK to %d for %d" % (self.node.hostname,self.source_address,self.destination_address,packet.ack_number))
        self.transport.send_packet(packet)
