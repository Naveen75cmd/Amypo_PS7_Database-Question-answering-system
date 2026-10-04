"""Resource monitoring, bandwidth simulation and the simulated cloud API.

This package is what makes the router resource-aware (and therefore *PS1*): it
reports live RAM and CPU, replays bandwidth scenarios, and models a
quota-limited cloud with pricing and failures. The cloud is entirely local —
``cloud_api`` never opens a socket.
"""

from .bandwidth import BandwidthSimulator, load_scenarios
from .cloud import CloudCall, SimulatedCloud
from .resources import ResourceMonitor, ResourceSnapshot

__all__ = [
    "BandwidthSimulator",
    "load_scenarios",
    "CloudCall",
    "SimulatedCloud",
    "ResourceMonitor",
    "ResourceSnapshot",
]
