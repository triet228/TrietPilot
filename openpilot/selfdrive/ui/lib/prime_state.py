from enum import IntEnum
import os
import threading

from openpilot.common.params import Params


class PrimeType(IntEnum):
  UNKNOWN = -2
  UNPAIRED = -1
  NONE = 0
  MAGENTA = 1
  LITE = 2
  BLUE = 3
  MAGENTA_NEW = 4
  PURPLE = 5


class PrimeState:
  """Offline stand-in for the comma prime status.

  TrietPilot never contacts comma's servers, so this never polls anything. The type
  comes from the PrimeType param or the PRIME_TYPE env var if set, otherwise the
  device is treated as unpaired. start() and stop() are kept so the UI code that
  drives the old poller keeps working unchanged.
  """

  def __init__(self):
    self._params = Params()
    self._lock = threading.Lock()
    self.prime_type = self._load_initial_state()

  def _load_initial_state(self):
    prime_type_str = os.getenv("PRIME_TYPE") or self._params.get("PrimeType")
    try:
      if prime_type_str is not None:
        return PrimeType(int(prime_type_str))
    except (ValueError, TypeError):
      pass
    return PrimeType.UNPAIRED

  def set_type(self, prime_type):
    with self._lock:
      if prime_type != self.prime_type:
        self.prime_type = prime_type
        self._params.put("PrimeType", int(prime_type))

  def start(self):
    pass

  def stop(self):
    pass

  def get_type(self):
    with self._lock:
      return self.prime_type

  def is_prime(self):
    with self._lock:
      return bool(self.prime_type > PrimeType.NONE)

  def is_full_prime(self):
    with self._lock:
      return self.prime_type > PrimeType.NONE and self.prime_type != PrimeType.LITE

  def is_paired(self):
    with self._lock:
      return self.prime_type > PrimeType.UNPAIRED
