"""Middleware to communicate with PubSub Message Broker."""
from collections.abc import Callable
from enum import Enum
from queue import LifoQueue, Empty
import socket
from typing import Any
import json
import pickle
import xml.etree.ElementTree as et

from src.protocol import PSProto


class MiddlewareType(Enum):
    """Middleware Type."""

    CONSUMER = 1
    PRODUCER = 2


class Queue:
    """Representation of Queue interface for both Consumers and Producers."""

    def __init__(self, topic, _type=MiddlewareType.CONSUMER):
        """Create Queue."""        
        self.topic = topic
        self.type = _type
        self.serial = 0
        self.address = (('localhost', 5000))

        self.sockM = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sockM.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sockM.connect(self.address)

    def push(self, value):
        """Sends data to broker."""
        if self.type == MiddlewareType.PRODUCER:       
            PSProto.send_msg(self.sockM, self.serial, PSProto.publish(self.topic, value))

    def pull(self):
        """Receives (topic, data) from broker.
        Should BLOCK the consumer!"""
        recv = PSProto.recv_msg(self.sockM)
        if recv:
            return recv.topic, recv.value
        else:
            return None

    def list_topics(self, callback: Callable):
        """Lists all topics available in the broker."""
        PSProto.send_msg(self.sockM, self.serial, PSProto.request_all_topic())
        
    def cancel(self):
        """Cancel subscription."""
        PSProto.send_msg(self.sockM, self.serial, PSProto.cancelTopic(self.topic))


class JSONQueue(Queue):
    """Queue implementation with JSON based serialization."""
    def __init__(self, topic, _type = MiddlewareType.CONSUMER):
        super().__init__(topic, _type)
        self.serial = 0
        
        if _type == MiddlewareType.CONSUMER: 
            PSProto.send_msg(self.sockM, self.serial, PSProto.subscribe(topic))

class XMLQueue(Queue):
    """Queue implementation with XML based serialization."""
    def __init__(self, topic, _type = MiddlewareType.CONSUMER):
        super().__init__(topic, _type)
        self.serial = 1
        
        if _type == MiddlewareType.CONSUMER:
            PSProto.send_msg(self.sockM, self.serial, PSProto.subscribe(topic))

class PickleQueue(Queue):
    """Queue implementation with Pickle based serialization."""
    def __init__(self, topic, _type = MiddlewareType.CONSUMER):
        super().__init__(topic, _type)
        self.serial = 2
        
        if _type == MiddlewareType.CONSUMER: 
            PSProto.send_msg(self.sockM, self.serial, PSProto.subscribe(topic))
        
