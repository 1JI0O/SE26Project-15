"""S10 spike rung: 10 -> 200 users in 10s, hold 2 min, fall back to 10.

Reuses SyncDevice so the traffic mix is identical to S1/S6 and the only variable is
the shape. The tail-off stage is the point of the scenario: it measures whether the
service recovers to its pre-spike latency once load drops, or stays degraded because
queues and the connection pool never drain.
"""

from __future__ import annotations

import sys
from pathlib import Path

from locust import LoadTestShape

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_sync import SyncDevice  # noqa: F401,E402  (registered as the user class)

BASELINE_USERS = 10
PEAK_USERS = 200
WARMUP_S = 60
RAMP_S = 10
HOLD_S = 120
RECOVER_S = 120


class SpikeShape(LoadTestShape):
    """Four stages: warm baseline, 10s ramp to peak, 2min hold, drop back to baseline."""

    def tick(self):
        t = self.get_run_time()
        ramp_end = WARMUP_S + RAMP_S
        hold_end = ramp_end + HOLD_S
        total = hold_end + RECOVER_S

        if t < WARMUP_S:
            return (BASELINE_USERS, BASELINE_USERS)
        if t < ramp_end:
            # 190 extra users over 10s = 19/s, which is the spike being tested.
            return (PEAK_USERS, 20)
        if t < hold_end:
            return (PEAK_USERS, 20)
        if t < total:
            # Locust sheds users instantly; recovery is measured on the server side.
            return (BASELINE_USERS, 50)
        return None
