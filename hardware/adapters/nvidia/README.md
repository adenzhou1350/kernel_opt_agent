# NVIDIA adapter

Use `scripts/discover_hardware.py` for a runtime snapshot.  It queries
`nvidia-smi`, optionally enriches the result with PyTorch device properties and
records whether `nvcc`, `ptxas`, `nvdisasm`, `cuobjdump`, `ncu` and `nsys` are
available.

Static and runtime evidence are optional capabilities.  Their absence must be
recorded and must weaken attribution; it must not be filled from another GPU.
