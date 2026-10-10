"""In-process stand-in for an MQTT broker, for tests that have no mosquitto.

FakeBroker routes publishes to subscribers using real MQTT topic matching and
keeps retained messages. FakeClient implements the slice of the paho Client
API that GcsReporter uses, so the reporter runs unmodified against it.
"""

import threading
from types import SimpleNamespace

import paho.mqtt.client as mqtt


class FakeBroker:
    def __init__(self):
        self._lock = threading.RLock()
        self._subs = []             # (filter, callback(msg))
        self._retained = {}
        self.published = []         # (topic, payload)

    def subscribe(self, topic_filter, callback):
        with self._lock:
            self._subs.append((topic_filter, callback))
            retained = [(t, p) for t, p in self._retained.items()
                        if mqtt.topic_matches_sub(topic_filter, t)]
        for topic, payload in retained:
            callback(SimpleNamespace(topic=topic, payload=payload))

    def publish(self, topic, payload, retain=False):
        with self._lock:
            self.published.append((topic, payload))
            if retain:
                self._retained[topic] = payload
            targets = [cb for f, cb in self._subs if mqtt.topic_matches_sub(f, topic)]
        msg = SimpleNamespace(topic=topic, payload=payload)
        for cb in targets:
            cb(msg)

    def client(self):
        return FakeClient(self)


class FakeClient:
    def __init__(self, broker: FakeBroker):
        self._broker = broker
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.host = None

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        pass

    def connect_async(self, host, port=1883, keepalive=60):
        self.host = (host, port)

    def loop_start(self):
        self.on_connect(self, None, {}, mqtt.MQTT_ERR_SUCCESS, None)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def subscribe(self, topic, qos=0):
        self._broker.subscribe(topic, lambda m: self.on_message(self, None, m))

    def publish(self, topic, payload, qos=0, retain=False):
        self._broker.publish(topic, payload, retain)
        return SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)
