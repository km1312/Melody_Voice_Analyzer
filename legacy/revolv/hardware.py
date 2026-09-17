"""Detect the machine's compute capability and pick pipeline settings to match.

Everything here is deliberately import-light at module level; torch is only
imported inside detect() so the GUI can start instantly and probe in a worker
thread.
"""

import os
from dataclasses import dataclass, field
from typing import List

# GPU tiers, richest first. Each entry is:
#   (minimum free VRAM in GB, whisper model, ctranslate2 compute type,
#    transcription batch size, device for the emotion model)
# The VRAM figures leave headroom for the alignment, diarization and emotion
# models, which sit in memory alongside the ASR model.
GPU_TIERS = [
    (15.0, "large-v3", "float16", 16, "cuda"),
    (11.0, "large-v3", "float16", 12, "cuda"),
    (8.0,  "large-v3", "float16", 8,  "cuda"),
    (6.0,  "large-v3", "int8_float16", 4, "cuda"),
    (4.5,  "medium",   "int8_float16", 4, "cpu"),
    (3.0,  "small",    "int8_float16", 4, "cpu"),
    (2.0,  "base",     "int8_float16", 2, "cpu"),
]

# CPU tiers, richest first: (min RAM GB, min cores, model, batch size)
CPU_TIERS = [
    (24.0, 12, "medium", 8),
    (16.0, 8,  "small",  8),
    (8.0,  4,  "base",   4),
    (0.0,  1,  "tiny",   2),
]

MODEL_CHOICES = ["auto", "large-v3", "large-v2", "medium", "small", "base", "tiny"]


@dataclass
class HardwareProfile:
    device: str = "cpu"
    device_name: str = "CPU"
    vram_gb: float = 0.0
    compute_capability: str = ""
    cpu_count: int = 1
    ram_gb: float = 0.0
    compute_type: str = "int8"
    model_size: str = "base"
    batch_size: int = 4
    emotion_device: str = "cpu"
    diarize_device: str = "cpu"
    cpu_threads: int = 4
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.device == "cuda":
            head = f"{self.device_name}  ({self.vram_gb:.1f} GB VRAM)"
        else:
            head = f"{self.device_name}  ({self.cpu_count} cores, {self.ram_gb:.1f} GB RAM)"
        return f"{head}\nModel {self.model_size} - {self.compute_type} - batch {self.batch_size}"


def _total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        pass
    try:  # Windows fallback without psutil
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullTotalPhys / 1024 ** 3
    except Exception:
        return 8.0


def _cpu_profile(profile: HardwareProfile) -> HardwareProfile:
    for min_ram, min_cores, model, batch in CPU_TIERS:
        if profile.ram_gb >= min_ram and profile.cpu_count >= min_cores:
            profile.model_size = model
            profile.batch_size = batch
            break
    profile.device = "cpu"
    profile.compute_type = "int8"
    profile.emotion_device = "cpu"
    profile.diarize_device = "cpu"
    # Leave a couple of cores for the OS and the UI thread.
    profile.cpu_threads = max(1, min(profile.cpu_count - 2, 16))
    return profile


def detect(device_override: str = "auto", model_override: str = "auto") -> HardwareProfile:
    """Probe the machine and return a tuned pipeline profile."""
    profile = HardwareProfile()
    profile.cpu_count = os.cpu_count() or 1
    profile.ram_gb = _total_ram_gb()

    try:
        import torch
    except Exception as exc:  # pragma: no cover - torch is a hard dependency
        profile.notes.append(f"PyTorch failed to load ({exc}); using CPU defaults.")
        return _cpu_profile(profile)

    try:
        profile.device_name = _cpu_name()
    except Exception:
        pass

    cuda_available = False
    try:
        cuda_available = torch.cuda.is_available()
    except Exception as exc:
        profile.notes.append(f"CUDA probe failed ({exc}).")

    if device_override == "cpu":
        profile.notes.append("Device forced to CPU in settings.")
        cuda_available = False

    if not cuda_available:
        if device_override == "cuda":
            profile.notes.append("CUDA was requested but is unavailable; falling back to CPU.")
        else:
            profile.notes.append("No CUDA GPU detected. Transcription will run on the CPU and will be slow.")
        _cpu_profile(profile)
    else:
        props = torch.cuda.get_device_properties(0)
        profile.device = "cuda"
        profile.device_name = props.name
        profile.vram_gb = props.total_memory / 1024 ** 3
        major, minor = torch.cuda.get_device_capability(0)
        profile.compute_capability = f"{major}.{minor}"
        profile.diarize_device = "cuda"
        profile.cpu_threads = max(1, min(profile.cpu_count - 2, 16))

        for min_vram, model, compute, batch, emotion_device in GPU_TIERS:
            if profile.vram_gb >= min_vram:
                profile.model_size = model
                profile.compute_type = compute
                profile.batch_size = batch
                profile.emotion_device = emotion_device
                break
        else:
            profile.notes.append(
                f"{profile.vram_gb:.1f} GB of VRAM is below the 2 GB minimum; using the CPU instead."
            )
            _cpu_profile(profile)
            profile.device_name = props.name + " (unused)"

        # ctranslate2 needs compute capability 7.0+ for real float16 throughput.
        if profile.device == "cuda" and major < 7:
            profile.compute_type = "int8"
            profile.notes.append(
                f"Compute capability {profile.compute_capability} predates fast float16; using int8."
            )

    if model_override and model_override != "auto":
        profile.model_size = model_override
        profile.notes.append(f"Model size overridden to {model_override} in settings.")

    return profile


def _cpu_name() -> str:
    try:
        import platform
        name = platform.processor() or platform.machine()
        return name or "CPU"
    except Exception:
        return "CPU"
