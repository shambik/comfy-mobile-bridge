"""The user's spill rules (issue #82; lab 2026-11-24, user: "After every spill restart comfy before its next job",
"For 5 seconds over 15 min is a cancel", the step limits, and 2026-11-25: "The spill rules should always be right user
should be able to choose to ignore them").

A spill on this 10 GB card is not visible in Windows' shared-GPU-memory counter (the app streams its models from RAM on
purpose); it shows as a GPU that is busy but starved: high utilisation at low power with the memory controller idle,
while weights stream over PCIe. Healthy H3 jobs here run ~270-280 W with the memory controller at 30-50 %; spilled ones
~135-150 W at 0-2 %.
"""
from __future__ import annotations

BUSY_PERCENT = 90          # the GPU reports itself busy...
STARVED_POWER_W = 180      # ...but draws little power...
STARVED_MEMORY_PERCENT = 10  # ...and its memory controller is nearly idle
SPILL_SECONDS = 60         # for this long = a spill
RECOVER_SECONDS = 30       # a spill ends after the GPU has been healthy this long
SHORT_JOB_SECONDS = 5.5    # a single clip this short...
SHORT_JOB_LIMIT = 15 * 60  # ...running longer than this is cancelled
HIGH_MP = 1.1              # above this counts as the 1.5 MP limits
# One sampling step, seconds: (clip seconds up to, megapixels up to 1.1) -> limit; the user's numbers for 10 s and 15 s.
# Shorter clips and long-take parts use the 10 s limits.
STEP_LIMITS = {(10, False): 200, (10, True): 450, (15, False): 400, (15, True): 1000}


def step_limit(clip_seconds: float, megapixels: float) -> int:
    """The step limit for one clip or one long-take part."""
    bucket = 10 if clip_seconds <= 10.5 else 15
    return STEP_LIMITS[(bucket, megapixels > HIGH_MP)]


class SpillWatch:
    """Fed one GPU sample at a time; counts consecutive starved seconds."""

    def __init__(self):
        self.starved_since: float | None = None
        self.healthy_since: float | None = None
        self.active = False           # spilling right now (stays on through a single healthy-looking reading)
        self.spilled = False          # a spill happened during this job (60 s or more starved)
        self.longest = 0.0
        self.last: dict | None = None

    def feed(self, sample: dict, now: float) -> bool:
        """True while the GPU is spilling right now (starved for SPILL_SECONDS or more)."""
        util = sample.get("gpu_util_percent")
        power = sample.get("gpu_power_w")
        memory = sample.get("gpu_memory_util_percent")
        starved = (util is not None and power is not None and memory is not None
                   and util >= BUSY_PERCENT and power < STARVED_POWER_W and memory < STARVED_MEMORY_PERCENT)
        if not starved:
            if self.active:
                self.healthy_since = self.healthy_since if self.healthy_since is not None else now
                if now - self.healthy_since >= RECOVER_SECONDS:
                    self.active, self.starved_since, self.healthy_since = False, None, None
                return self.active
            self.starved_since = None
            return False
        self.healthy_since = None
        if self.starved_since is None:
            self.starved_since = now
        seconds = now - self.starved_since
        self.longest = max(self.longest, seconds)
        if seconds >= SPILL_SECONDS:
            self.active = self.spilled = True
            self.last = {"gpu_util_percent": util, "gpu_power_w": power, "gpu_memory_util_percent": memory}
        return self.active


class StepClock:
    """Times the current sampling step. Only real steps count: a step counter with a total above zero. Start-up,
    model loading and a resumed batch report no total yet and are never timed (2026-11-25: timing "step 0/0" canceled
    a healthy resumed long take)."""

    def __init__(self):
        self.key: tuple[int, int] | None = None
        self.since: float | None = None

    def feed(self, step: int, total: int, now: float) -> float:
        """Seconds the current step has run (0 when there is no real step)."""
        if total <= 0:
            self.key, self.since = None, None
            return 0.0
        key = (int(step), int(total))
        if key != self.key:
            self.key, self.since = key, now
        return now - (self.since or now)


def rule_cancel_reason(*, step_seconds: float, step: int, total: int, limit: int, single_short_job: bool,
                       running_seconds: float) -> str | None:
    """The reason to cancel under the rules, or None."""
    if total > 0 and step_seconds > limit:
        return (f"Canceled by the spill rules: sampling step {step + 1}/{total} ran {step_seconds:.0f} s, over the "
                f"{limit} s limit. Turn on \"No limits\" to let a job like this run.")
    if single_short_job and running_seconds > SHORT_JOB_LIMIT:
        return (f"Canceled by the spill rules: a 5 s clip ran {running_seconds / 60:.0f} min, over the 15 min limit. "
                "Turn on \"No limits\" to let a job like this run.")
    return None
