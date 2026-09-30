"""Convert two consecutive Radiacode RawData half-second bins to one count."""
from datetime import datetime, timezone
import math


class PairRawData:
    def __init__(self):
        self.pending = None
        self.last_dt = None
        self.sequence = 0
        self.discarded = 0

    def add(self, record, received_utc_ns, received_monotonic_ns, session_id, serial):
        # The recorded hour had 0.49/0.51 s bins and integer count_rate/2.
        # Device dt is useful for continuity, never as an absolute UTC clock.
        dt = record.dt
        rate = float(record.count_rate)
        if not math.isfinite(rate) or rate < 0 or not math.isclose(rate / 2, round(rate / 2), rel_tol=0, abs_tol=1e-5):
            self.pending = None
            self.discarded += 1
            return None
        if self.last_dt is not None:
            gap = (dt - self.last_dt).total_seconds()
            if not 0.4 <= gap <= 0.6:
                self.pending = None
                self.discarded += 1
            if gap <= 0:
                return None
        self.last_dt = dt
        half_count = int(round(rate / 2))
        if self.pending is None:
            self.pending = (half_count, dt)
            return None
        first_count, first_dt = self.pending
        self.pending = None
        self.sequence += 1
        return {
            "schema_version": "ares-radiacode-counts-1",
            "source": "radiacode_usb", "kind": "one_second_count",
            "session_id": session_id, "serial_number": serial,
            "sequence": self.sequence, "cps": first_count + half_count,
            "exposure_s": 1.0, "device_bin_start": first_dt.isoformat(),
            "device_bin_end": dt.isoformat(),
            "received_utc_ns": received_utc_ns,
            "received_monotonic_ns": received_monotonic_ns,
            "timestamp_utc": datetime.fromtimestamp(received_utc_ns / 1e9, timezone.utc).isoformat(),
            "time_basis": "host_receipt_of_second_half_bin",
        }
