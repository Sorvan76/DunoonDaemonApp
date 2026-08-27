"""One gate for all requests to Dunoon's configured primary model."""
import threading

PRIMARY_INFERENCE_LOCK = threading.RLock()
