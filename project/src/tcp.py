import sys
sys.path.append('..')

from sim import Sim
from connection import Connection
from tcppacket import TCPPacket
from buffer import SendBuffer,ReceiveBuffer


class TCP(Connection):
    ''' A TCP connection between two hosts.'''
    def __init__(self,transport,source_address,source_port,destination_address,destination_port,app=None):
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
        self.min_rtt = 1

        self.alpha = 0.125
        self.beta = 0.25

        ### Sender functionality

        self.transmission_finished = False

        # send buffer
        self.send_buffer = SendBuffer()
        # maximum segment size, in bytes
        self.mss = 1000
        # send window; represents the total number of bytes that may
        # be outstanding at one time
        self.window = self.mss
        # largest sequence number that has been ACKed so far; represents
        # the next sequence number the client expects to receive
        self.sequence = 0
        # retransmission timer
        self.timer = None
        # timeout duration in seconds
        self.timeout = 1
        # is_retransmitting prevents more duplicate ACKs from triggering another send.
        self.is_retransmitting = False

        self.force_drop = True

        ### Congestion Control

        self.threshold = 100000
        self.additive_increase_total = 0

        # Fast Retransmit ACKs
        self.retransmit_acks = [-1] * 3

        Sim.set_debug("Link")

        ### Receiver functionality

        # receive buffer
        self.receive_buffer = ReceiveBuffer()
        # ack number to send; represents the largest in-order sequence
        # number not yet received
        self.ack = 0

        ### FILE WRITING
        self.write_to_file = False

        if self.write_to_file:
            sys.stdout = open('output.txt', 'w')
            print "# Time (seconds) Sequence (number) Dropped (0 or 1) ACK (0 or 1)"

    ### Global Methods
    def trace(self,message):
        ''' Print debugging messages. '''
        if not self.write_to_file:
            Sim.trace("TCP",message)

    def plot(self, sequence_number, isACK = False, dropped=False):
        message = "%i %i %d" % (sequence_number, dropped, isACK)

        if self.write_to_file:
            Sim.trace("TCP", message)

    ### Congestion Control Methods

    def is_threshold_reached(self):
        self.trace("CURRENT THRESHOLD: %d" % self.threshold)
        return self.window >= self.threshold

    def slowstart_increment_cwnd(self, bytes_acknowledged):
        self.window += bytes_acknowledged
        self.trace("Window (Slow Start) == %d" % self.window)

    def additiveincrease_increment_cwnd(self, bytes_acknowledged):
        additive_increase = self.get_additive_increase(bytes_acknowledged)
        self.window += additive_increase
        self.trace("Window (AI) == %d" % self.window)

    # Add up increase until it's >= self.mss (1000), then return that amount.
    def get_additive_increase(self, bytes_acknowledged):
        increase = (self.mss * bytes_acknowledged / self.window)
        self.additive_increase_total += increase

        if self.additive_increase_total >= self.mss:
            self.additive_increase_total -= self.mss
            return self.mss
        else:
            self.trace("ADDITIVE INCREASE STORED: %d" % increase)
            return 0


    def reset_fastretransmit_acks(self):
        self.retransmit_acks = [-1] * 3

    def is_fast_retransmit(self, ack_num):
        self.retransmit_acks[2] = self.retransmit_acks[1]
        self.retransmit_acks[1] = self.retransmit_acks[0]
        self.retransmit_acks[0] = ack_num

        self.trace("FAST RETRANSMIT: %i, %i, %i" % (self.retransmit_acks[0], self.retransmit_acks[1], self.retransmit_acks[2]))

        return self.retransmit_acks[0] == self.retransmit_acks[1] and self.retransmit_acks[0] == self.retransmit_acks[2]

    def execute_loss_event(self):
        self.threshold = max(self.window / 2, self.mss)
        self.window = self.mss
        self.additive_increase_total = 0
        self.trace("NEW THRESHOLD: %d" % self.threshold)

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
        if self.rto < self.min_rtt:
            self.rto = self.min_rtt
        elif self.rto > self.max_rtt:
            self.rto = self.max_rtt

    def receive_packet(self,packet):
        ''' Receive a packet from the network layer. '''
        if packet.ack_number > 0:
            # handle ACK
            self.handle_ack(packet)
        if packet.length > 0:
            # handle data
            self.handle_data(packet)

    def halt_if_finished(self):
        if self.send_buffer.available() == 0 and self.send_buffer.outstanding() == 0:
            self.trace("-------> ENDING <-------")
            self.cancel_timer()
            return True
        return False

    ''' Sender '''

    def send(self,data):
        ''' Send data on the connection. Called by the application. This
            code currently sends all data immediately. '''
        self.send_buffer.put(data)
        # self.trace("Data added to buffer.")
        self.send_next_packet_if_possible()

    def send_next_packet_if_possible(self):
        if self.halt_if_finished():
            return

        while self.send_buffer.available() > 0 \
                and self.send_buffer.outstanding() < self.window:
            new_data, new_sequence = self.send_buffer.get(self.mss)
            self.send_packet(new_data, new_sequence)
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

        if sequence == 32000 and self.force_drop:
            self.trace(">>> PACKET DROPPED: %d <<<" % sequence)
            self.plot(packet.sequence,dropped=True)
            self.force_drop = False
            return

        self.trace("%s (%d) sending TCP segment to %d for %d" % (self.node.hostname,self.source_address,self.destination_address,packet.sequence))
        self.transport.send_packet(packet)
        self.plot(packet.sequence)

    def handle_ack(self,packet):
        rtt = Sim.scheduler.current_time() - packet.sent_time
        self.trace("ACK RECEIVED: %d; RTT: %s" % (packet.ack_number, rtt))
        self.send_buffer.slide(packet.ack_number)

        if self.halt_if_finished():
            return

        self.plot(packet.ack_number, isACK=True)

        acked_byte_count = packet.ack_number - self.sequence
        self.sequence = packet.ack_number

        if self.is_retransmitting is False and self.is_fast_retransmit(packet.ack_number):
            self.is_retransmitting = True
            self.trace("PACKETS 1: %d; 2: %d; 3: %d" % (self.retransmit_acks[0], self.retransmit_acks[1], self.retransmit_acks[2]))
            self.retransmit(None)
            return
        elif self.is_retransmitting and acked_byte_count is 0:
            return

        self.is_retransmitting = False

        if self.is_threshold_reached():
            self.trace("---> ACKED BYTE COUNT: %d" % acked_byte_count)
            self.additiveincrease_increment_cwnd(acked_byte_count)
        else:
            self.slowstart_increment_cwnd(acked_byte_count)

        self.send_next_packet_if_possible()
        self.calculate_rtt(rtt)

        if self.send_buffer.available() >= 0 or self.send_buffer.outstanding() > 0:
            self.restart_timer()
        else:
            self.cancel_timer()

    def retransmit(self,event):
        if self.halt_if_finished():
            return

        self.trace(">>>> WARNING: Timer expired.")

        self.backoff_timer()
        self.restart_timer(timer_expired = True)
        resend_data, resend_sequence = self.send_buffer.resend(self.mss)
        self.send_packet(resend_data, resend_sequence)

        # Reset for slow start.
        self.reset_fastretransmit_acks()
        self.execute_loss_event()

        if not event:
            self.trace("%s (%d) retransmission timer fired" % (self.node.hostname,self.source_address))

    def restart_timer(self, timer_expired = False):
        self.trace("WARNING: Restarting timer.")

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
        self.trace("%s (%d) received TCP segment from %d; Seq: %d, Ack: %d" % (self.node.hostname,packet.destination_address,packet.source_address,packet.sequence,packet.ack_number))
        self.receive_buffer.put(packet.body, packet.sequence)

        # SEND DATA TO APPLICATION
        data, last_sequence_number = self.receive_buffer.get()
        self.ack = last_sequence_number + len(data)
        self.app.receive_data(data)

        self.send_ack(current_time=packet.sent_time, packet_sequence=packet.sequence)

    def send_ack(self, current_time, packet_sequence):
        ''' Send an ack. '''
        packet = TCPPacket(source_address=self.source_address,
                           source_port=self.source_port,
                           destination_address=self.destination_address,
                           destination_port=self.destination_port,
                           sequence=packet_sequence,
                           ack_number=self.ack,
                           sent_time=current_time)

        self.trace("%s (%d) sending TCP ACK to %d for %d" % (self.node.hostname,self.source_address,self.destination_address,packet.ack_number))
        self.transport.send_packet(packet)
