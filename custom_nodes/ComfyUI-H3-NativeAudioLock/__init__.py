"""Local H3 node for keeping a user supplied audio track exact.

The node is intentionally small and self-contained.  It follows ComfyUI's
public MODEL/LATENT/AUDIO contracts and leaves the normal H3 nodes untouched.
"""

import torch
import torch.nn.functional as F
import torchaudio

import comfy.nested_tensor


class MiniMaxH3NativeAudioLock:
    """Encode user audio, lock its latent, and denoise only the video latent."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "av_latent": ("LATENT",),
                "audio_vae": ("VAE",),
                "audio": ("AUDIO",),
            }
        }

    RETURN_TYPES = ("MODEL", "LATENT", "AUDIO")
    RETURN_NAMES = ("model", "av_latent", "exact_audio")
    FUNCTION = "lock_audio"
    CATEGORY = "MiniMax H3/Native Audio"
    DESCRIPTION = (
        "Keep the uploaded audio exact while H3 denoises the video latent."
    )

    def lock_audio(self, model, av_latent, audio):
        samples = av_latent.get("samples")
        if samples is None or not getattr(samples, "is_nested", False):
            raise ValueError("MiniMax H3 requires a joint AV latent for exact-audio mode")

        video_latent, audio_template = samples.unbind()[:2]
        waveform = audio["waveform"][:1]
        source_rate = int(audio["sample_rate"])
        target_rate = int(getattr(self._audio_vae, "audio_sample_rate", 32000))
        if source_rate != target_rate:
            waveform = torchaudio.functional.resample(waveform, source_rate, target_rate)

        audio_vae = self._audio_vae
        encoded_audio = audio_vae.encode(waveform.movedim(1, -1))
        target_length = audio_template.shape[-1]
        if encoded_audio.shape[-1] > target_length:
            encoded_audio = encoded_audio[..., :target_length]
        elif encoded_audio.shape[-1] < target_length:
            encoded_audio = F.pad(encoded_audio, (0, target_length - encoded_audio.shape[-1]))

        locked_latent = dict(av_latent)
        locked_latent["samples"] = comfy.nested_tensor.NestedTensor(
            (video_latent, encoded_audio)
        )
        locked_latent["noise_mask"] = comfy.nested_tensor.NestedTensor(
            (torch.ones_like(video_latent), torch.zeros_like(encoded_audio))
        )

        patched_model = model.clone()
        options = patched_model.model_options.get("transformer_options", {}).copy()
        options["minimax_h3_lock_audio_clean"] = True
        patched_model.model_options["transformer_options"] = options
        return patched_model, locked_latent, audio

    def _bind_audio_vae(self, audio_vae):
        self._audio_vae = audio_vae


class MiniMaxH3NativeAudioLockWithVAE(MiniMaxH3NativeAudioLock):
    """ComfyUI passes the VAE as an input; bind it before the main operation."""

    def lock_audio(self, model, av_latent, audio_vae, audio):
        self._bind_audio_vae(audio_vae)
        return super().lock_audio(model, av_latent, audio)


NODE_CLASS_MAPPINGS = {
    "MiniMaxH3NativeAudioLock": MiniMaxH3NativeAudioLockWithVAE,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MiniMaxH3NativeAudioLock": "MiniMax H3 Native Exact-Audio Lock",
}
