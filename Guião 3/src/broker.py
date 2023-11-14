
"""Message Broker"""
import enum
from typing import Dict, List, Any, Tuple
import socket
import selectors

from src.protocol import PSProto


class Serializer(enum.Enum):
    """Possible message serializers."""

    JSON = 0
    XML = 1
    PICKLE = 2


class Broker:
    """Implementation of a PubSub Message Broker."""
    
    def __init__(self):
        """Initialize broker."""
        self.canceled = False
        self._host = "localhost"
        self._port = 5000

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self._host, self._port))
        self.sock.listen()

        self.sel = selectors.DefaultSelector()
        self.sel.register(self.sock, selectors.EVENT_READ, self.accept)

        self.topic_lastmsg = {}        
        self.consum_serlz = {}       
        self.subs_per_topic = {}    

    def accept(self, sock, mask):
        """Accept a connection and store it's serialization type."""
        conn, addr = sock.accept()          
        
        self.sel.register(conn, selectors.EVENT_READ, self.read)

    def read(self, conn, mask):
        """Handle further operations"""

        recv = PSProto.recv_msg(conn)

        if not recv:
            self.unsubscribe("", conn)
            self.sel.unregister(conn)
            conn.close()
            return

        if recv.type == "Subscribe":
            if conn in self.consum_serlz:
                self.subscribe(recv.topic, conn, self.consum_serlz[conn])
            else:
                self.subscribe(recv.topic, conn, None)
        elif recv.type == "Publish":
            self.put_topic(recv.topic, recv.value)
            if recv.topic in self.subs_per_topic:
                for tup in self.list_subscriptions(recv.topic):
                    PSProto.send_msg(tup[0], self.consum_serlz[tup[0]], recv)
            else:
                self.subs_per_topic[recv.topic] = []
        elif recv.type == "CancelSubscription":
            self.unsubscribe(recv.topic, conn)


    def list_topics(self) -> List[str]:
        """Returns a list of strings containing all topics containing values."""
        list_topics = []
        for topic in self.topic_lastmsg.keys():
            if self.topic_lastmsg[topic] is not None:
                list_topics.append(topic)
        return list_topics

    def get_topic(self, topic):
        """Returns the currently stored value in topic."""
        if topic in self.topic_lastmsg:
            return self.topic_lastmsg[topic]
        
        return None

    def put_topic(self, topic, value):
        """Store in topic the value."""

        if topic not in list(self.topic_lastmsg):
            contained_topics = [t for t in list(self.topic_lastmsg) if topic.startswith(t)]
           
            self.subs_per_topic[topic] = []
            if len(contained_topics) > 0:
                
                for t in contained_topics:
                    for consumer in self.subs_per_topic[t]:
                        if consumer not in self.subs_per_topic[topic]:
                            self.subs_per_topic[topic].append(consumer)

        self.topic_lastmsg[topic] = value

    def list_subscriptions(self, topic: str) -> List[Tuple[socket.socket, Serializer]]:
        """Provide list of subscribers to a given topic."""
        lst = []
        for addr in self.subs_per_topic[topic]:
            if self.consum_serlz[addr] == 0:
                serial = Serializer.JSON
            elif self.consum_serlz[addr] == 1:
                serial = Serializer.XML
            elif self.consum_serlz[addr] == 2:   
                serial = Serializer.PICKLE

            lst.append((addr, serial))

        return lst

    def subscribe(self, topic: str, address: socket.socket, _format: Serializer = None):
        """Subscribe to topic by client in address."""

        if address not in self.consum_serlz:
            if _format == Serializer.JSON or _format is None:
                self.consum_serlz[address] = 0
            elif _format == Serializer.XML:
                self.consum_serlz[address] = 1
            elif _format == Serializer.PICKLE:
                self.consum_serlz[address] = 2

        self.put_topic(topic, None)

        if topic not in self.subs_per_topic:
            contained_topics = [t for t in self.topic_lastmsg if topic.startswith(t)]
            self.subs_per_topic[topic] = contained_topics

        if address not in self.subs_per_topic[topic]:
            self.subs_per_topic[topic].append(address)

        if topic in self.topic_lastmsg and self.topic_lastmsg[topic] is not None:
            PSProto.send_msg(address, self.consum_serlz[address], PSProto.publish(topic, self.topic_lastmsg[topic]))


    def unsubscribe(self, topic, address):
        """Unsubscribe to topic by client in address."""
        #percorrer todos os topicos e remover o address de cada um
        for t in list(self.topic_lastmsg):
            if address in self.subs_per_topic[t]:
                
                self.subs_per_topic[t].remove(address)

            if t == topic:
                self.topic_lastmsg.pop(t)
           
    def run(self):
        """Run until canceled."""
        while not self.canceled:
            events = self.sel.select()
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)