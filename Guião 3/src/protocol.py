import json
import pickle
import xml.etree.ElementTree as et
import enum
import socket


class Message:
    """Base message."""

    def __init__(self, type):
        self.type = type

class Subscribe(Message):
    """Message to subscribe a topic."""

    def __init__(self, topic):
        super().__init__("Subscribe")
        self.topic = topic

    def __repr__(self):
        dic = {"type": self.type, "topic": self.topic}
        return json.dumps(dic)

    def toXML(self):
        return "<data type=\"{}\" topic=\"{}\"></data>".format(self.type, self.topic)

    def toPickle(self):
        dic = {"type": self.type, "topic": self.topic}
        return pickle.dumps(dic)

class Publish(Message):
    """Message to publish on a topic"""

    def __init__(self, topic, value):
        super().__init__("Publish")
        self.topic = topic
        self.value = value

    def __repr__(self):
        dic = {"type": self.type, "topic": self.topic, "value": self.value}
        return json.dumps(dic)

    def toXML(self):
        return "<data type=\"{}\" topic=\"{}\" value=\"{}\"></data>".format(self.type, self.topic, self.value)

    def toPickle(self):
        dic = {"type": self.type, "topic": self.topic, "value": self.value}
        return pickle.dumps(dic)

class RequestAllTopic(Message):
    """Message to request the topic list."""

    def __init__(self):
        super().__init__("request_all_topics")

    def __repr__(self):
        dic = {"type": self.type}
        return json.dumps(dic)


    def toXML(self):
        return "<data type=\"{}\"></data>".format(self.type)

    def toPickle(self):
        dic = {"type": self.type}
        return pickle.dumps(dic)

class CancelTopic(Message):
    """Message to cancel a subscription on a topic"""

    def __init__(self, topic):
        super().__init__("CancelSubscription")
        self.topic = topic

    def __repr__(self):
        dic = {"type": self.type, "topic": self.topic}
        return json.dumps(dic)

    def toXML(self):
        return "<data type=\"{}\" topic=\"{}\"></data>".format(self.type, self.topic)

    def toPickle(self):
        dic = {"type": self.type, "topic": self.topic}
        return pickle.dumps(dic)


class PSProto:
    @classmethod
    def subscribe(cls, topic) -> Subscribe:
        return Subscribe(topic)

    @classmethod
    def publish(cls, topic, value) -> Publish:
        return Publish(topic, value) 

    @classmethod
    def request_all_topic(self) -> RequestAllTopic:
        return RequestAllTopic()

    @classmethod
    def cancelTopic(self, topic) -> CancelTopic:
        return CancelTopic(topic)


    @classmethod
    def send_msg(self, conn: socket, serializer, msg: Message):
        """Send a message."""
        #send serializer
        conn.send(serializer.to_bytes(1, 'big'))            
        if serializer == 0:
            msg = msg.__repr__().encode('utf-8')  
            conn.send(len(msg).to_bytes(2, 'big'))        
            conn.send(msg)                                

        elif serializer == 1:
            msg = msg.toXML().encode('utf-8')               
            conn.send(len(msg).to_bytes(2, 'big'))           
            conn.send(msg)                                   
        elif serializer == 2:
            msg = msg.toPickle()       
            conn.send(len(msg).to_bytes(2, 'big'))    
            conn.send(msg)                               

    @classmethod
    def recv_msg(self, conn: socket) -> Message:
        """Receive a message."""

        serializer = int.from_bytes(conn.recv(1), 'big')    
        header = int.from_bytes(conn.recv(2), 'big')            
        if header == 0: return None

        try:
            if serializer == 0:
                recv = conn.recv(header).decode('utf-8')    
                             
                msg_dic = json.loads(recv)
            elif serializer == 1 :
                recv = conn.recv(header).decode('utf-8')     

                msg_dic = {}                                     
                root = et.fromstring(recv)
                for element in root.keys():
                    msg_dic[element] = root.get(element)

            elif serializer == 2:
                recv = conn.recv(header)                     
                msg_dic = pickle.loads(recv)                  


        except:
            pass

        if msg_dic["type"] == "Subscribe":
            return self.subscribe(msg_dic["topic"])
        elif msg_dic["type"] == "Publish":
            return self.publish(msg_dic["topic"], msg_dic["value"])
        elif msg_dic["type"] == "TopicListRequest":
            return self.request_all_topic()
        elif msg_dic["type"] == "CancelSubscription":
            return self.cancelTopic(msg_dic["topic"])
        else:
            return None


class PSProtoBadFormat(Exception):
    """Exception when source message is not PubSubProtocol"""

    def __init__(self, original_msg: bytes=None) :
        """Store original message that triggered exception."""
        self._original = original_msg

    @property
    def original_msg(self) -> str:
        """Retrieve original message as a string."""
        return self._original.decode("utf-8")