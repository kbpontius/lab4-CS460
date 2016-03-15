import optparse
import sys

import matplotlib
from pylab import *

# Parses a file of rates and plot a sequence number graph. Black
# squares indicate a sequence number being sent and dots indicate a
# sequence number being ACKed.
class Plotter:
    def __init__(self,file):
        """ Initialize plotter with a file name. """
        self.file = file
        self.data = []
        self.min_time = None
        self.max_time = None

        self.dropX = []
        self.dropY = []
        self.x = []
        self.y = []
        self.ackX = []
        self.ackY = []

    def parse(self):
        """ Parse the data file """
        first = None
        f = open(self.file)
        for line in f.readlines():
            if line.startswith("#"):
                continue
            try:
                t,sequence,dropped = line.split()
            except:
                continue
            t = float(t)
            sequence = int(sequence)
            dropped = int(dropped)
            self.data.append((t,sequence,dropped))
            if not self.min_time or t < self.min_time:
                self.min_time = t
            if not self.max_time or t > self.max_time:
                self.max_time = t

    def load_data(self):
        """ Create a sequence graph of the packets. """
        clf()
        figure(figsize=(15,5))
        for (t,sequence,dropped) in self.data:
            # print("%d, %d, %d" % (t, sequence,dropped))
            if dropped == 1:
                self.dropX.append(t)
                self.dropY.append((sequence / 1000) % 50)
                continue

            self.x.append(t)
            self.y.append((sequence / 1000) % 50)
            # pretend the ACK came 0.2 seconds later
            self.ackX.append(t + 0.2)
            self.ackY.append((sequence / 1000) % 50)

    def plot(self):            
        scatter(self.dropX,self.dropY,marker='x',s=100)
        scatter(self.x,self.y,marker='s',s=5)
        scatter(self.ackX,self.ackY,marker='s',s=0.2)
        xlabel('Time (seconds)')
        ylabel('(Sequence Number / 1000) Mod 1500')
        # xlim([self.min_time,3])
        xlim([self.min_time,self.max_time])
        savefig('sequence.png')

def parse_options():
        # parse options
        parser = optparse.OptionParser(usage = "%prog [options]",
                                       version = "%prog 0.1")

        parser.add_option("-f","--file",type="string",dest="file",
                          default=None,
                          help="file")

        (options,args) = parser.parse_args()
        return (options,args)


if __name__ == '__main__':
    (options,args) = parse_options()
    if options.file == None:
        print "plot.py -f file"
        sys.exit()
    p = Plotter(options.file)
    p.parse()
    p.load_data()
    p.plot()
