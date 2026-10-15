# Autograd call-arity controls

This tiny CPU probe checks the installed Torch engine, not an upstream operator.
It distinguishes an omitted default argument from an explicitly passed default:
both run the same Python forward body, but their autograd input counts differ.
The negative control also confirms that returning too few gradients is rejected;
an extra trailing `None` is accepted by the tested Torch engine.

Run `test_apply_arity.py` with an existing Torch environment and CUDA hidden. No
installation, model weights or CUDA initialization is needed. Inspect actual
`Function.apply` call sites before transferring the finding to another project.

For a tensor-subclass hypothesis, these controls do **not** prove that the
subclass gradient branch is reachable, that its storage aliases are valid, or
that squeezed gradient shapes are handled correctly. Those require the real
operator and its native environment. Do not report this probe as a reproduction
of TransformerEngine or as evidence that its split/backward implementation is
correct.
