import logging
import time

logger = logging.getLogger("llm_security_platform.circuit_breaker")


class CircuitBreakerOpenException(Exception):
    pass


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 15.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.last_state_change = time.time()

    def record_success(self):
        self.failure_count = 0
        if self.state != "CLOSED":
            logger.info(f"Circuit Breaker for '{self.name}' transitioned from {self.state} to CLOSED")
            self.state = "CLOSED"
            self.last_state_change = time.time()

    def record_failure(self):
        self.failure_count += 1
        logger.warning(f"Circuit Breaker for '{self.name}' registered failure {self.failure_count}/{self.failure_threshold}")
        if self.failure_count >= self.failure_threshold and self.state != "OPEN":
            logger.error(f"Circuit Breaker for '{self.name}' transitioned to OPEN (Failing Fast)")
            self.state = "OPEN"
            self.last_state_change = time.time()

    def allow_request(self) -> bool:
        current_time = time.time()
        if self.state == "OPEN":
            if current_time - self.last_state_change > self.recovery_timeout:
                logger.info(f"Circuit Breaker for '{self.name}' entered HALF-OPEN state to test service recovery")
                self.state = "HALF_OPEN"
                self.last_state_change = current_time
                return True
            return False
        return True
