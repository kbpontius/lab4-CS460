import sys
sys.path.append('..')

from src.sim import Sim
from src.connection import Connection
from src.tcppacket import TCPPacket
from src.buffer import SendBuffer,ReceiveBuffer


class TCP(Connection):
    ''' A TCP connection between two hosts.'''
    def __init__(self,transport,source_address,source_port,destination_address,destination_port,app=None,window=15000):
        Connection.__init__(self,transport,source_address,source_port, destination_address,destination_port,app)

        ### RTO Timer Properties
        self.rtt_initialized = False
        self.rto = None
        self.srtt = None
        self.rttvar = None
        self.K = 4
        self.initialize_timer()

        # RTT Cap Seconds
        self.max_rtt = 60

        self.alpha = 0.125
        self.beta = 0.25

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

        ### Congestion Control
        self.threshold = 100000
        self.ack_1 = -1
        self.ack_2 = -1
        self.ack_3 = -1

        ### Receiver functionality

        # receive buffer
        self.receive_buffer = ReceiveBuffer()
        # ack number to send; represents the largest in-order sequence
        # number not yet received
        self.ack = 0

    ### Congestion Control Methods

    def restart_cwnd(self):
        self.window = self.mss

    def slowstart_incremenet_cwnd(self, bytes_acknowledged):
        self.window += bytes_acknowledged

        threshold_reached = self.window >= self.threshold
        return threshold_reached

    def additiveincrease_increment_cwnd(self, bytes_acknowledged):
        self.window += (self.mss * bytes_acknowledged/ self.window)

    def is_fast_retransmit(self, ack_num):
        self.ack_3 = self.ack_2
        self.ack_2 = self.ack_1
        self.ack_1 = ack_num

        return self.ack_1 == self.ack_2 and self.ack_1 == self.ack_3

    def execute_loss_event(self):
        self.threshold = max(self.window / 2, self.mss)
        self.window = self.mss
        
    ### General Methods

    def initialize_timer(self):
        self.rto = 3

    def calculate_rtt(self, rtt):
        if self.rtt_initialized is False:
            self.calculate_first_rtt(rtt)
            self.rtt_initialized = True
        else:
            self.calculate_ongoing_rtt(rtt)

    def calculate_first_rtt(self, new_rtt):
        self.srtt = new_rtt
        self.rttvar = new_rtt / 2
        self.rto = self.srtt + self.K * self.rttvar

    def calculate_ongoing_rtt(self, new_rtt):
        self.rttvar = (1 - self.beta) * self.rttvar + self.beta * abs(self.srtt - new_rtt)
        self.srtt = (1 - self.alpha) * self.srtt + self.alpha * new_rtt
        self.rto = self.srtt + self.K * self.rttvar
        self.validate_timer()

    def backoff_timer(self):
        self.rto *= 2
        self.validate_timer()

    def validate_timer(self):
        if self.rto < 1:
            self.rto = 1
        elif self.rto > self.max_rtt:
            self.rto = self.max_rtt

    def trace(self,message):
        ''' Print debugging messages. '''
        # Sim.trace("TCP",message)

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
        # self.trace("Data added to buffer.")
        self.send_next_packet_if_possible()

    def send_next_packet_if_possible(self):
        while self.send_buffer.available() > 0 and self.send_buffer.outstanding() < self.window:
            new_data, new_sequence = self.send_buffer.get(self.mss)
            self.send_packet(new_data, new_sequence)
            # message = ("Window not full (") + str(self.send_buffer.outstanding()) + (") sent packet: " + str(new_sequence))
            # self.trace(message)
            self.restart_timer()

    def send_packet(self,data,sequence):
        current_time = Sim.scheduler.current_time()

        packet = TCPPacket(source_address=self.source_address,
                           source_port=self.source_port,
                           destination_address=self.destination_address,
                           destination_port=self.destination_port,
                           body=data,
                           sequence=sequence,
                           ack_number=self.ack,
                           sent_time=current_time)

        # send the packet
        # self.trace("%s (%d) sending TCP segment to %d for %d" % (self.node.hostname,self.source_address,self.destination_address,packet.sequence))
        self.transport.send_packet(packet)

    # TODO: Reset timer when all packets are sent and new data is received.
    def handle_ack(self,packet):
        rtt = Sim.scheduler.current_time() - packet.sent_time
        # self.trace("ACK RECEIVED: %d; RTT: %s" % (packet.ack_number, rtt))
        self.send_buffer.slide(packet.ack_number)
        self.send_next_packet_if_possible()
        self.calculate_rtt(rtt)
        self.restart_timer()

    def retransmit(self,event):
        ''' Retransmit data. '''
        # self.trace("WARNING: Timer expired.")

        self.backoff_timer()
        self.restart_timer(timer_expired=True)
        resend_data, resend_sequence = self.send_buffer.resend(self.mss)
        self.send_packet(resend_data, resend_sequence)
        # self.trace("%s (%d) retransmission timer fired" % (self.node.hostname,self.source_address))

    def restart_timer(self, timer_expired = False):
        # self.trace("WARNING: Restarting timer.")

        if self.send_buffer.available() == 0 and self.send_buffer.outstanding() == 0:
            self.cancel_timer()
        else:
            # self.trace("AVAILBLE: %d; OUTSTANDING: %d" % (self.send_buffer.available(), self.send_buffer.outstanding()))
            self.start_timer(timer_expired)

    def start_timer(self, timer_expired = False):
        # self.trace("WARNING: Starting timer.")
        if timer_expired == False:
            self.cancel_timer()

        self.timer = Sim.scheduler.add(delay=self.rto, event='retransmit', handler=self.retransmit)

    def cancel_timer(self):
        ''' Cancel the timer. '''
        if not self.timer:
            return
        # self.trace("WARNING: Cancelling timer.")
        Sim.scheduler.cancel(self.timer)
        self.timer = None

    ''' Receiver '''

    def handle_data(self,packet):
        ''' Handle incoming data. This code currently gives all data to
            the application, regardless of whether it is in order, and sends
            an ACK.'''
        # self.trace("%s (%d) received TCP segment from %d; Seq: %d, Ack: %d" % (self.node.hostname,packet.destination_address,packet.source_address,packet.sequence,packet.ack_number))
        self.receive_buffer.put(packet.body, packet.sequence)

        if self.ack == packet.sequence:
            self.ack += packet.length
            # self.trace("Sent ACK: " + str(self.ack))

        # SEND DATA TO APPLICATION
        data, last_sequence_number = self.receive_buffer.get()
        self.app.receive_data(data)
        self.send_ack(current_time=packet.sent_time)

    def send_ack(self, current_time):
        ''' Send an ack. '''
        packet = TCPPacket(source_address=self.source_address,
                           source_port=self.source_port,
                           destination_address=self.destination_address,
                           destination_port=self.destination_port,
                           sequence=self.sequence,
                           ack_number=self.ack,
                           sent_time=current_time)
        # send the packet
        # self.trace("%s (%d) sending TCP ACK to %d for %d" % (self.node.hostname,self.source_address,self.destination_address,packet.ack_number))
        self.transport.send_packet(packet)
