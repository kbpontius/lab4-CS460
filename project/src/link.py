from sim import Sim

import random

class Link(object):
    def __init__(self,address=0,startpoint=None,endpoint=None,queue_size=None,
                 bandwidth=1000000.0,propagation=0.001,loss=0):
        self.running = True
        self.address = address
        self.startpoint = startpoint
        self.endpoint = endpoint
        self.queue_size = queue_size
        self.bandwidth = bandwidth
        self.propagation = propagation
        self.loss = loss
        self.busy = False
        self.queue = []

    def trace_link(self,message):
        Sim.trace("Link",message)

    def trace_queue(self, message):
        Sim.trace("Queue", message)

    ## Handling packets ##

    def send_packet(self,packet):
        # check if link is running
        if not self.running:
            return
        # drop packet due to queue overflow
        if self.queue_size and len(self.queue) == self.queue_size:
            self.trace_queue("x")
            return
        # drop packet due to random loss
        if self.loss > 0 and random.random() < self.loss:
            if self.address == 1:
                self.trace_link("%i 1 0" % (packet.sequence))
                self.trace_queue("x")
            return

        packet.enter_queue = Sim.scheduler.current_time()

        if len(self.queue) == 0 and not self.busy:
            # packet can be sent immediately
            self.busy = True
            self.transmit(packet)
        else:
            # add packet to queue
            self.queue.append(packet)
            self.trace_queue_size()

        return
        
    def transmit(self,packet):
        packet.queueing_delay += Sim.scheduler.current_time() - packet.enter_queue
        delay = (8.0*packet.length)/self.bandwidth
        packet.transmission_delay += delay
        packet.propagation_delay += self.propagation
        # schedule packet arrival at end of link
        Sim.scheduler.add(delay=delay+self.propagation,event=packet,handler=self.endpoint.receive_packet)
        # schedule next transmission
        Sim.scheduler.add(delay=delay,event='finish',handler=self.next)

    def next(self,event):
        if len(self.queue) > 0:
            packet = self.queue.pop(0)
            self.trace_queue_size()
            self.transmit(packet)
        else:
            self.busy = False

    def down(self,event):
        self.running = False

    def up(self,event):
        self.running = True

    def trace_queue_size(self):
        self.trace_queue("%i" % len(self.queue))