""" Chord DHT node implementation. """
import socket
import threading
import logging
import pickle
from utils import dht_hash, contains


class FingerTable:
    """Finger Table."""

    def __init__(self, node_id, node_addr, m_bits=10):
        """ Initialize Finger Table."""
        self.node_id = node_id
        self.node_addr = node_addr
        self.m_bits = m_bits
        self.finger_table = {}

        for i in range(m_bits):
            id = self.node_id + 2**i

            if id > 2**m_bits:
                #no caso de i ser maior que 2**m_bits
                id = id % 2**m_bits

            self.finger_table[i] = (id,node_addr)


    def fill(self, node_id, node_addr):
        """ Fill all entries of finger_table with node_id, node_addr."""
        for i in self.finger_table:
            self.finger_table[i] = (node_id, node_addr)

    def update(self, index, node_id, node_addr):
        """Update index of table with node_id and node_addr."""
       
        self.finger_table[index-1] = (node_id, node_addr)

    def find(self, identification):
        """ Get node address of closest preceding node (in finger table) of identification. """
        #se identification estiver na lista de ids
        ids_addr = tuple(self.finger_table.values())
        for i in range(len(ids_addr)):
            if ids_addr[i][0] == identification:
            # if contains(self.node_id, ids_addr[i][0], identification):
                return ids_addr[i-1][1]
  
        #se não estiver
        mais_peq = True
        menor_dif = 1000 #valor inicial
        for i in ids_addr:
            if identification - i[0] < menor_dif and identification > i[0]:
                menor_dif = identification - i[0]
                #o numero não é o mais pequeno
                mais_peq = False
        
        indx = identification - menor_dif

        maior = 0
        if mais_peq:
            for i in ids_addr:
                if i[0] > maior:
                    maior = i[0]
            indx = maior
        
        for i in ids_addr:
            if i[0] == indx:
                return i[1]

    def refresh(self):
        """ Retrieve finger table entries requiring refresh."""
 
        refreshed = []
        for i in range(self.m_bits):
            id = self.node_id + 2**i

            if id > 2**self.m_bits:
                #no caso de i ser maior que 2**m_bits
                id = id % 2**self.m_bits

            refreshed.append((i+1, id, self.finger_table[i][1]))

        return refreshed

    def getIdxFromId(self, id):
    
        refresh = self.refresh()

        for i in range(self.m_bits):
            if contains(self.node_id, refresh[i][1], id):
                return i + 1


    def __repr__(self):
        return "FingerTable: " + str(self.finger_table)
        

    @property
    def as_list(self):
        """return the finger table as a list of tuples: (identifier, (host, port)).
        NOTE: list index 0 corresponds to finger_table index 1
        """
        tuple_as_list = []
        for i in range(len(self.finger_table)):
            tuple_as_list.append((self.finger_table[i][0], self.finger_table[i][1]))

        return tuple_as_list
        
class DHTNode(threading.Thread):
    """ DHT Node Agent. """

    def __init__(self, address, dht_address=None, timeout=3):
        """Constructor

        Parameters:
            address: self's address
            dht_address: address of a node in the DHT
            timeout: impacts how often stabilize algorithm is carried out
        """
        threading.Thread.__init__(self)
        self.done = False
        self.identification = dht_hash(address.__str__())
        self.addr = address  # My address
        self.dht_address = dht_address  # Address of the initial Node
        if dht_address is None:
            self.inside_dht = True
            # I'm my own successor
            self.successor_id = self.identification
            self.successor_addr = address
            self.predecessor_id = None
            self.predecessor_addr = None
        else:
            self.inside_dht = False
            self.successor_id = None
            self.successor_addr = None
            self.predecessor_id = None
            self.predecessor_addr = None

        # self.finger_table = None    #TODO create finger_table
        self.finger_table = FingerTable(self.identification, self.addr)

        self.keystore = {}  # Where all data is stored
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(timeout)
        self.logger = logging.getLogger("Node {}".format(self.identification))

    def send(self, address, msg):
        """ Send msg to address. """
        payload = pickle.dumps(msg)
        self.socket.sendto(payload, address)

    def recv(self):
        """ Retrieve msg payload and from address."""
        try:
            payload, addr = self.socket.recvfrom(1024)
        except socket.timeout:
            return None, None

        if len(payload) == 0:
            return None, addr
        return payload, addr

    def node_join(self, args):
        """Process JOIN_REQ message.

        Parameters:
            args (dict): addr and id of the node trying to join
        """

        self.logger.debug("Node join: %s", args)
        addr = args["addr"]
        identification = args["id"]
        if self.identification == self.successor_id:  # I'm the only node in the DHT
            self.successor_id = identification
            self.successor_addr = addr

            #TODO update finger table
            self.finger_table.fill(self.successor_id, self.successor_addr)
            #TODO

            args = {"successor_id": self.identification, "successor_addr": self.addr}
            self.send(addr, {"method": "JOIN_REP", "args": args})

        elif contains(self.identification, self.successor_id, identification):

            args = {
                "successor_id": self.successor_id,
                "successor_addr": self.successor_addr,
            }
            self.successor_id = identification
            self.successor_addr = addr

            #TODO update finger table
            self.finger_table.fill(self.successor_id, self.successor_addr)
            #TODO

            self.send(addr, {"method": "JOIN_REP", "args": args})
        else:
            self.logger.debug("Find Successor(%d)", args["id"])
            self.send(self.successor_addr, {"method": "JOIN_REQ", "args": args})
        self.logger.info(self)

    def get_successor(self, args):
        """Process SUCCESSOR message.

        Parameters:
            args (dict): addr and id of the node asking
        """

        self.logger.debug("Get successor: %s", args)
        #TODO Implement processing of SUCCESSOR message
        
        id_ = args["id"]
        addr = args["from"]

        if(contains(self.identification, self.successor_id, id_)):
            self.send(addr, {"method": "SUCCESSOR_REP", "args": {"req_id": id_, "successor_id": self.successor_id, "successor_addr": self.successor_addr}})
        else:
            self.send(self.finger_table.find(id_), {"method": "SUCCESSOR", "args": {"id": id_, "from": addr}})
        #TODO

    def notify(self, args):
        """Process NOTIFY message.
            Updates predecessor pointers.

        Parameters:
            args (dict): id and addr of the predecessor node
        """

        self.logger.debug("Notify: %s", args)
        if self.predecessor_id is None or contains(
            self.predecessor_id, self.identification, args["predecessor_id"]
        ):
            self.predecessor_id = args["predecessor_id"]
            self.predecessor_addr = args["predecessor_addr"]
        self.logger.info(self)

    def stabilize(self, from_id, addr):
        """Process STABILIZE protocol.
            Updates all successor pointers.

        Parameters:
            from_id: id of the predecessor of node with address addr
            addr: address of the node sending stabilize message
        """

        self.logger.debug("Stabilize: %s %s", from_id, addr)
        if from_id is not None and contains(self.identification, self.successor_id, from_id):
            # Update our successor
            self.successor_id = from_id
            self.successor_addr = addr

            #TODO update finger table
            self.finger_table.fill(self.successor_id, self.successor_addr)
            #TODO

        # notify successor of our existence, so it can update its predecessor record
        args = {"predecessor_id": self.identification, "predecessor_addr": self.addr}
        self.send(self.successor_addr, {"method": "NOTIFY", "args": args})


        # TODO refresh finger_table
        for i in self.finger_table.refresh():
            args = {"id": i[1], "from": self.addr}
            self.send(i[2], {"method": "SUCCESSOR", "args": args})

        #TODO

    def put(self, key, value, address):
        """Store value in DHT.

        Parameters:
        key: key of the data
        value: data to be stored
        address: address where to send ack/nack
        """
        key_hash = dht_hash(key)
        self.logger.debug("Put: %s %s", key, key_hash)

        #TODO Replace next code:

        #messages
        ack = {"method": "ACK"}
        nack = {"method": "NACK"}
        put_message = {"method": "PUT", "args": {"key": key, "value": value, "from": address}}

        # if key_hash is in the range of the node
        if contains(self.predecessor_id, self.identification, key_hash):

            # if key is not in the keystore
            if self.keystore.get(key) is None:
                self.send(address, ack)
                self.keystore[key] = value

            else:
                self.send(address, nack)

        # if key_hash is in the range of the successor
        elif contains(self.identification, self.successor_id, key_hash):
            self.send(self.successor_addr, put_message)

        else:
            # send to successor / without finger table
            # self.send(self.successor_addr, put_message)

            # send to closest node in finger table
            self.send(self.finger_table.find(key_hash), put_message)

    def get(self, key, address):
        """Retrieve value from DHT.

        Parameters:
        key: key of the data
        address: address where to send ack/nack
        """
        key_hash = dht_hash(key)
        self.logger.debug("Get: %s %s", key, key_hash)

        #TODO Replace next code:

        #messages
        nack = {"method": "NACK"}
        get_message = {"method": "GET", "args": {"key": key, "from": address}}

        # if key_hash is in the range of the node
        if contains(self.predecessor_id, self.identification, key_hash):

            if self.keystore.get(key) is not None:

                ack = {'method': 'ACK', "args": self.keystore[key]}
                self.send(address, ack)
            else:
                self.send(address, nack)

        # if key_hash is in the range of the sucessors node
        elif contains(self.identification, self.successor_id, key_hash):
            self.send(self.successor_addr, get_message)
        else:
            #send to successor
            # self.send(self.successor_addr, get_message)

            #send to closest node in finger table
            self.send(self.finger_table.find(key_hash), get_message)


    def run(self):
        self.socket.bind(self.addr)

        # Loop untiln joining the DHT
        while not self.inside_dht:
            join_msg = {
                "method": "JOIN_REQ",
                "args": {"addr": self.addr, "id": self.identification},
            }
            self.send(self.dht_address, join_msg)
            payload, addr = self.recv()
            if payload is not None:
                output = pickle.loads(payload)
                self.logger.debug("O: %s", output)
                if output["method"] == "JOIN_REP":
                    args = output["args"]
                    self.successor_id = args["successor_id"]
                    self.successor_addr = args["successor_addr"]
                    #TODO fill finger table
                    self.finger_table.fill(self.successor_id, self.successor_addr)

                    self.inside_dht = True
                    self.logger.info(self)

        while not self.done:
            payload, addr = self.recv()
            if payload is not None:
                output = pickle.loads(payload)
                self.logger.info("O: %s", output)
                if output["method"] == "JOIN_REQ":
                    self.node_join(output["args"])
                elif output["method"] == "NOTIFY":
                    self.notify(output["args"])
                elif output["method"] == "PUT":
                    self.put(
                        output["args"]["key"],
                        output["args"]["value"],
                        output["args"].get("from", addr),
                    )
                elif output["method"] == "GET":
                    self.get(output["args"]["key"], output["args"].get("from", addr))
                elif output["method"] == "PREDECESSOR":
                    # Reply with predecessor id
                    self.send(
                        addr, {"method": "STABILIZE", "args": self.predecessor_id}
                    )
                elif output["method"] == "SUCCESSOR":
                    # Reply with successor of id
                    self.get_successor(output["args"])
                elif output["method"] == "STABILIZE":
                    # Initiate stabilize protocol
                    self.stabilize(output["args"], addr)
                elif output["method"] == "SUCCESSOR_REP":
                    #TODO Implement processing of SUCCESSOR_REP
                    self.finger_table.update(self.finger_table.getIdxFromId(output["args"]["req_id"]), output["args"]["successor_id"], output["args"]["successor_addr"])

                    # pass
            else:  # timeout occurred, lets run the stabilize algorithm
                # Ask successor for predecessor, to start the stabilize process
                self.send(self.successor_addr, {"method": "PREDECESSOR"})

    def __str__(self):
        return "Node ID: {}; DHT: {}; Successor: {}; Predecessor: {}; FingerTable: {}".format(
            self.identification,
            self.inside_dht,
            self.successor_id,
            self.predecessor_id,
            self.finger_table,
        )

    def __repr__(self):
        return self.__str__()
