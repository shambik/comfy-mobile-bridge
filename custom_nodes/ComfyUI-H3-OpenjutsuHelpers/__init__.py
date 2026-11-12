"""H3 Openjutsu helpers (bridge code, MIT): the hair eraser for the Openjutsu character swap (issue #58).

A bald character (or one with different hair) inherits the source person's hair silhouette from Openjutsu's grey
mannequin motion reference. The bridge erases that person's hair from the mannequin before H3 sees it:

H3KeepMaskedArea  flat grey outside the (grown) mask, so a text-prompted SAM detection sees only that person.
                  Measured 2026-11-12 on The Last Fold: "hair" over the whole frame found only the woman's long hair;
                  on the man alone it found his curls on every frame.
H3MaskMultiply    a * b, b resized to a's size (MaskComposite needs equal sizes).
H3InpaintArea     fills the masked area of every frame from its surroundings (OpenCV Telea inpainting).

Needs OpenCV (cv2) in ComfyUI's Python.
"""
import cv2
import numpy as np
import torch
import torch.nn.functional as F


def _frames_mask(mask, n, h, w):
    m = mask.reshape(-1, mask.shape[-2], mask.shape[-1]).float()
    m = F.interpolate(m[:, None], size=(h, w), mode="bilinear")[:, 0]
    if m.shape[0] == 1:
        m = m.expand(n, -1, -1)
    if m.shape[0] < n:
        raise ValueError(f"{m.shape[0]} mask frames for {n} images")
    return m[:n]


class H3KeepMaskedArea:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "mask": ("MASK", {"tooltip": "White = keep; everything else becomes flat grey."}),
            "grow_px": ("INT", {"default": 24, "min": 0, "max": 128, "tooltip": "Grow the kept area (image pixels)."}),
        }}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "keep"
    CATEGORY = "conditioning/minimax/openjutsu"

    def keep(self, images, mask, grow_px):
        n, h, w = images.shape[:3]
        m = _frames_mask(mask, n, h, w)[:, None]
        if grow_px:
            m = F.max_pool2d(m, 2 * grow_px + 1, stride=1, padding=grow_px)
        m = (m[:, 0] > 0.5).float()[..., None].to(images.device)
        return ((images * m + 0.5 * (1 - m)).to(images.dtype),)


class H3MaskMultiply:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"a": ("MASK",), "b": ("MASK", {"tooltip": "Resized to a's size."})}}

    RETURN_TYPES = ("MASK",)
    FUNCTION = "multiply"
    CATEGORY = "conditioning/minimax/openjutsu"

    def multiply(self, a, b):
        a = a.reshape(-1, a.shape[-2], a.shape[-1]).float()
        return (a * _frames_mask(b, a.shape[0], a.shape[1], a.shape[2]).to(a.device),)


class H3InpaintArea:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "mask": ("MASK", {"tooltip": "White = fill from the surroundings; any size, one mask per frame or one."}),
            "grow_px": ("INT", {"default": 6, "min": 0, "max": 64, "tooltip": "Grow the mask first (image pixels)."}),
            "radius": ("INT", {"default": 9, "min": 1, "max": 64, "tooltip": "Telea inpainting radius (pixels)."}),
        }}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "fill"
    CATEGORY = "conditioning/minimax/openjutsu"

    def fill(self, images, mask, grow_px, radius):
        n, h, w = images.shape[:3]
        m = _frames_mask(mask, n, h, w)
        kernel = np.ones((2 * grow_px + 1, 2 * grow_px + 1), np.uint8) if grow_px else None
        out = images.clone()
        filled = 0
        for i in range(n):
            area = (m[i] > 0.5).cpu().numpy().astype(np.uint8) * 255
            if kernel is not None:
                area = cv2.dilate(area, kernel)
            if not area.any():
                continue
            filled += 1
            frame = (images[i].cpu().numpy().clip(0, 1) * 255).astype(np.uint8)
            out[i] = torch.from_numpy(cv2.inpaint(frame, area, radius, cv2.INPAINT_TELEA).astype(np.float32) / 255.0
                                      ).to(out.dtype)
        print(f"[H3InpaintArea] filled the masked area in {filled} of {n} frames")
        return (out,)


NODE_CLASS_MAPPINGS = {"H3KeepMaskedArea": H3KeepMaskedArea, "H3MaskMultiply": H3MaskMultiply,
                       "H3InpaintArea": H3InpaintArea}
NODE_DISPLAY_NAME_MAPPINGS = {"H3KeepMaskedArea": "H3 Keep Masked Area", "H3MaskMultiply": "H3 Mask Multiply (resize)",
                              "H3InpaintArea": "H3 Inpaint Area (Telea)"}
