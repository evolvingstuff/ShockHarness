# Waiting for jobs

Every caller decides how long to wait for a job: `wait_for` has no default
timeout, and a call without one is a programming error.
