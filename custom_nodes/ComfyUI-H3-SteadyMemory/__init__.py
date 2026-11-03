"""Local H3 node that keeps VRAM below the point where the card starts spilling.

On a 10 GB card under Windows, a Sage H3 job runs 2-4x slower once VRAM use reaches about 9.75 GB: the GPU
keeps moving data over PCIe and power falls to about 140 W, while the output stays identical. See
docs/HARDWARE_AND_VRAM.md. For one sampling run this node turns off async weight offload and makes attention
wait for the GPU between steps, so temporary buffers are reused instead of growing the pool.

Nothing changes for jobs without this node: the state is set only around their own sampling.
"""

import functools

import torch

import comfy.ldm.minimax.model as h3
import comfy.model_management
import comfy.patcher_extension

WRAPPER_KEY = "h3_steady_memory"
state = {"active": False}


def sync():
    if state["active"]:
        torch.cuda.synchronize()


def wait_after(original):
    @functools.wraps(original)
    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        sync()
        return result
    return run


def wait_around(original):
    @functools.wraps(original)
    def run(*args, **kwargs):
        sync()
        result = original(*args, **kwargs)
        sync()
        return result
    return run


h3.optimized_attention = wait_around(h3.optimized_attention)
h3._mod_scale_shift = wait_after(h3._mod_scale_shift)
h3._mod_gate = wait_after(h3._mod_gate)
h3.Attention.forward = wait_after(h3.Attention.forward)
h3.MLP.forward = wait_after(h3.MLP.forward)


def steady_sampling(executor, *args, **kwargs):
    streams = comfy.model_management.NUM_STREAMS
    comfy.model_management.NUM_STREAMS = 0
    state["active"] = True
    try:
        return executor(*args, **kwargs)
    finally:
        state["active"] = False
        comfy.model_management.NUM_STREAMS = streams


class H3SteadyMemory:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",)}}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "MiniMax H3"
    DESCRIPTION = "Keep VRAM below the spill point for this model's sampling: async offload off, attention waits for the GPU."

    def patch(self, model):
        patched = model.clone()
        patched.add_wrapper_with_key(comfy.patcher_extension.WrappersMP.OUTER_SAMPLE, WRAPPER_KEY, steady_sampling)
        return (patched,)


NODE_CLASS_MAPPINGS = {"H3SteadyMemory": H3SteadyMemory}
NODE_DISPLAY_NAME_MAPPINGS = {"H3SteadyMemory": "MiniMax H3 Steady Memory"}
