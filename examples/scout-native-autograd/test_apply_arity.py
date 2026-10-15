"""CPU mechanism controls, NOT a TransformerEngine regression or qualification.

Run with an existing Torch environment and CUDA hidden:
  CUDA_VISIBLE_DEVICES='' python -B test_apply_arity.py
No downloaded source, tensor-subclass substitution or accelerator is required.
"""

import unittest

import torch


class ArityControl(torch.autograd.Function):
    @staticmethod
    def forward(ctx, tensor, axis, returned_count, squeeze=False):
        ctx.returned_count = returned_count
        return tensor.clone()

    @staticmethod
    def backward(ctx, gradient):
        return (gradient,) + (None,) * (ctx.returned_count - 1)


class ApplyArityTests(unittest.TestCase):
    def run_case(self, supplied, returned):
        tensor = torch.ones(2, requires_grad=True)
        args = (tensor, 0, returned) + (False,) * (supplied - 3)
        ArityControl.apply(*args).sum().backward()
        torch.testing.assert_close(tensor.grad, torch.ones_like(tensor))

    def test_omitted_default_requires_three_results(self):
        self.run_case(3, 3)

    def test_extra_trailing_none_is_accepted(self):
        self.run_case(3, 4)

    def test_explicit_default_requires_four_results(self):
        with self.assertRaisesRegex(RuntimeError, "expected 4, got 3"):
            self.run_case(4, 3)

    def test_explicit_default_with_four_results(self):
        self.run_case(4, 4)


if __name__ == "__main__":
    print(f"Torch {torch.__version__}; CPU mechanism controls only", flush=True)
    unittest.main(verbosity=2)
