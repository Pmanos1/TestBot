# app/pubsub.py
from broadcaster import Broadcast

# single, shared in-memory broadcaster
broadcast = Broadcast("memory://")
