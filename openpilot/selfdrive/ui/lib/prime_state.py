# openpilot/selfdrive/ui/lib/prime_state.py

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


class Provider(str):
  GOOGLE = "google"
  GITHUB = "github"
  APPLE = "apple"


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
    self._prime_trial_available = False
    self._commacare = False
    self._pairing_provider = os.getenv("PAIRING_PROVIDER") or self._params.get("PairingProvider")
    self._pairing_email = self._params.get("PairingEmail")

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

  def can_claim_prime_trial(self):
    return False

  def has_commacare(self):
    return False

  def get_pairing_provider(self):
    with self._lock:
      return self._pairing_provider if self.prime_type > PrimeType.UNPAIRED else None

  def get_pairing_account(self):
    with self._lock:
      if self.prime_type <= PrimeType.UNPAIRED or not self._pairing_provider:
        return "unknown"
      if self._pairing_provider == Provider.GITHUB or not self._pairing_email:
        return f"{self._pairing_provider} account"
      return self._pairing_email
