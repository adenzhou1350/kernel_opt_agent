"""Synthetic topology tests; no installed driver, executable, or GPU is needed."""

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hardware_topology.py"
SPEC = importlib.util.spec_from_file_location("hardware_topology", SCRIPT)
topology = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(topology)

DEVICES = [
    {"index": 7, "uuid": "GPU-seven", "name": "Seven"},
    {"index": 2, "uuid": "GPU-two", "name": "Two"},
]
IDENTITIES = "2, GPU-two\n7, GPU-seven\n"
MATRIX = """        GPU7 GPU2 NIC0 CPU Affinity NUMA Affinity GPU NUMA ID
GPU2    NV4  X    PHB  32-63,96-127 1 N/A
NIC0    PIX  PHB  X
GPU7    X    NV4  PIX  0-31,64-95 0 N/A

Legend:
  X = Self
  PIX = Connection traversing a single PCIe switch
  NV# = Connection traversing a bonded set of # NVLinks
NIC Legend:
  NIC0: mlx5_0
"""


class HardwareTopologyTests(unittest.TestCase):
    @staticmethod
    def completed(stdout="", stderr="", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def inspect(self, responses, devices=None, available=True):
        with (
            patch.object(
                topology.shutil,
                "which",
                return_value="/tools/nvidia-smi" if available else None,
            ),
            patch.object(topology.subprocess, "run", side_effect=responses) as run,
        ):
            result = topology.inspect_topology(DEVICES if devices is None else devices)
        self.assertEqual(len(result["evidence"]["commands"]), run.call_count)
        for call, evidence in zip(run.call_args_list, result["evidence"]["commands"]):
            timeout = 10 if call.args[0][1:] == ["topo", "-m"] else 2
            self.assertEqual(call.kwargs["timeout"], timeout)
            self.assertEqual(evidence["timeout_seconds"], timeout)
            self.assertFalse(call.kwargs.get("shell", False))
            self.assertEqual(call.args[0][0], "/tools/nvidia-smi")
            self.assertIn(
                call.args[0][1:],
                [
                    ["--query-gpu=index,uuid", "--format=csv,noheader,nounits"],
                    ["topo", "-m"],
                ],
            )
        self.assertLessEqual(run.call_count, 3)
        identity_args = ["--query-gpu=index,uuid", "--format=csv,noheader,nounits"]
        self.assertEqual(
            [call.args[0][1:] for call in run.call_args_list],
            [identity_args, ["topo", "-m"], identity_args][: run.call_count],
        )
        if result["status"] != "OBSERVED":
            self.assertEqual(result["affinities"], {})
        return result, run

    def inspect_matrix(self, matrix, before=IDENTITIES, after=IDENTITIES):
        return self.inspect(
            [self.completed(before), self.completed(matrix), self.completed(after)]
        )

    def test_sparse_indices_reordered_rows_nic_and_affinities(self):
        result, run = self.inspect_matrix(MATRIX, after="7, GPU-seven\n2, GPU-two\n")
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["raw"], MATRIX)
        self.assertEqual(
            result["evidence"]["gpu_labels"], {"GPU2": "GPU-two", "GPU7": "GPU-seven"}
        )
        self.assertEqual(
            result["edges"],
            [
                {
                    "source": "GPU-seven",
                    "target": "GPU-two",
                    "relationship": "NV4",
                    "bandwidth_bytes_per_second": None,
                },
                {
                    "source": "GPU-seven",
                    "target": "NIC0",
                    "relationship": "PIX",
                    "bandwidth_bytes_per_second": None,
                },
                {
                    "source": "GPU-two",
                    "target": "NIC0",
                    "relationship": "PHB",
                    "bandwidth_bytes_per_second": None,
                },
            ],
        )
        self.assertTrue(any("non-GPU" in value for value in result["unknowns"]))
        self.assertEqual(run.call_count, 3)
        self.assertEqual(result["evidence"]["commands"][1]["stdout"], MATRIX)
        self.assertEqual(
            result["affinities"],
            {
                "GPU-two": {
                    "cpu_affinity": "32-63,96-127",
                    "numa_affinity": "1",
                    "gpu_numa_id": "N/A",
                },
                "GPU-seven": {
                    "cpu_affinity": "0-31,64-95",
                    "numa_affinity": "0",
                    "gpu_numa_id": "N/A",
                },
            },
        )

    def test_sgr_header_and_real_style_tab_padding_preserve_raw(self):
        matrix = (
            "\t\x1b[4mGPU7\tGPU2\tNIC0\tCPU Affinity\tNUMA Affinity"
            "\tGPU NUMA ID\x1b[0m\r\n"
            "GPU2\tNV18\t X \tPHB\t32-63,96-127\t1\t\tN/A\r\n"
            "NIC0\tPIX\tPHB\t X \t\t\t\t\r\n"
            "GPU7\t X \tNV18\tPIX\t0-31,64-95\t0\t\tN/A\r\n"
            "\r\nLegend:\r\n  X = Self\r\n"
        )
        result, _ = self.inspect_matrix(matrix)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["raw"], matrix)
        self.assertEqual(result["evidence"]["commands"][1]["stdout"], matrix)
        self.assertEqual(result["edges"][0]["relationship"], "NV18")
        self.assertEqual(len(result["edges"]), 3)
        self.assertEqual(
            result["affinities"]["GPU-two"],
            {
                "cpu_affinity": "32-63,96-127",
                "numa_affinity": "1",
                "gpu_numa_id": "N/A",
            },
        )

    def test_only_sgr_controls_are_removed(self):
        matrix = "GPU2 GPU7\nGPU2 X \x1b[1;32mSYS\x1b[m\nGPU7 SYS X\n"
        result, _ = self.inspect_matrix(matrix)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["raw"], matrix)
        for control in (
            "\x1b[2J",  # Clear screen, not SGR.
            "\x1b[1A",  # Move cursor, not SGR.
            "\x1b]0;title\x07",  # Operating system command.
            "\x1b[?4m",  # Private/unsupported SGR syntax.
            "\x1b[4",  # Incomplete escape sequence.
            "\x00",
            "\x08",
            "\x0b",
            "\x0c",
            "\r",  # Bare carriage return, not a CRLF line ending.
            "\x7f",
            "\x85",
            "\x9b4m",
        ):
            for placement in ("header", "affinity", "legend"):
                with self.subTest(control=control, placement=placement):
                    if placement == "header":
                        invalid = control + MATRIX
                    elif placement == "affinity":
                        invalid = MATRIX.replace("N/A", control + "N/A", 1)
                    else:
                        invalid = MATRIX + control
                    result, _ = self.inspect_matrix(invalid)
                    self.assertEqual(result["status"], "UNAVAILABLE")
                    self.assertEqual(result["edges"], [])
                    self.assertEqual(result["raw"], invalid)
                    self.assertTrue(
                        any(
                            "Unsupported control" in value
                            for value in result["unknowns"]
                        )
                    )

    def test_legacy_nic_labels_remain_unverified_matrix_labels(self):
        for nic in ("mlx5_0", "mlx5_12", "irdma0", "irdma12"):
            with self.subTest(nic=nic):
                matrix = MATRIX.replace("NIC0", nic)
                result, _ = self.inspect_matrix(matrix)
                self.assertEqual(result["status"], "OBSERVED")
                self.assertEqual(result["raw"], matrix)
                self.assertEqual(len(result["edges"]), 3)
                self.assertEqual(result["edges"][1]["target"], nic)
                self.assertEqual(result["edges"][1]["relationship"], "PIX")
                self.assertTrue(
                    any(
                        "not independently verified" in value
                        for value in result["unknowns"]
                    )
                )

    def test_nvlink_involving_non_gpu_labels_is_rejected(self):
        for nic in ("NIC0", "mlx5_0", "irdma0"):
            for nic_first in (False, True):
                with self.subTest(nic=nic, nic_first=nic_first):
                    nodes = (
                        [nic, "GPU2", "GPU7"] if nic_first else ["GPU2", "GPU7", nic]
                    )
                    # Sanitized reproduction of an anomalous all-NV8 matrix.
                    matrix = "\t\x1b[4m" + "\t".join(nodes) + "\x1b[0m\n"
                    matrix += "".join(
                        source
                        + "\t"
                        + "\t".join(
                            "X" if source == target else "NV8" for target in nodes
                        )
                        + "\n"
                        for source in reversed(nodes)
                    )
                    result, _ = self.inspect_matrix(matrix)
                    self.assertEqual(result["status"], "UNAVAILABLE")
                    self.assertEqual(result["edges"], [])
                    self.assertEqual(result["raw"], matrix)
                    self.assertTrue(
                        any(
                            "NVLink relationship involves a non-GPU" in value
                            for value in result["unknowns"]
                        )
                    )

    def test_nvlink_between_nics_is_rejected(self):
        matrix = (
            "GPU2 GPU7 mlx5_0 irdma0\n"
            "GPU2 X NV8 PHB PHB\n"
            "GPU7 NV8 X PHB PHB\n"
            "mlx5_0 PHB PHB X NV8\n"
            "irdma0 PHB PHB NV8 X\n"
        )
        result, _ = self.inspect_matrix(matrix)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["raw"], matrix)
        self.assertTrue(
            any(
                "NVLink relationship involves a non-GPU" in value
                for value in result["unknowns"]
            )
        )

    def test_empty_and_na_affinities_stay_explicit(self):
        matrix = (
            "\tGPU7\tGPU2\tNIC0\tCPU Affinity\tNUMA Affinity\tGPU NUMA ID\n"
            "GPU2\tNV4\tX\tPHB\t\t1\tN/A\n"
            "NIC0\tPIX\tPHB\tX\n"
            "GPU7\tX\tNV4\tPIX\tN/A\t\t\n"
        )
        result, _ = self.inspect_matrix(matrix)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(
            result["affinities"],
            {
                "GPU-two": {
                    "cpu_affinity": "",
                    "numa_affinity": "1",
                    "gpu_numa_id": "N/A",
                },
                "GPU-seven": {
                    "cpu_affinity": "N/A",
                    "numa_affinity": "",
                    "gpu_numa_id": "",
                },
            },
        )
        self.assertEqual(result["raw"], matrix)
        self.assertEqual(len(result["edges"]), 3)

    def test_empty_affinity_tail_does_not_imply_zero(self):
        matrix = "GPU2 GPU7 CPU Affinity NUMA Affinity\nGPU2 X SYS\nGPU7 SYS X\n"
        result, _ = self.inspect_matrix(matrix)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(
            result["affinities"],
            {
                "GPU-two": {"cpu_affinity": "", "numa_affinity": ""},
                "GPU-seven": {"cpu_affinity": "", "numa_affinity": ""},
            },
        )

    def test_ambiguous_missing_affinity_cell_is_rejected(self):
        result, _ = self.inspect_matrix(MATRIX.replace("32-63,96-127 1 N/A", "1 N/A"))
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["edges"], [])
        self.assertTrue(any("Ambiguous" in value for value in result["unknowns"]))

    def test_supported_connectivity_tokens_without_affinities(self):
        for relationship in ("SYS", "NODE", "PHB", "PXB", "PIX", "NV1", "NV18"):
            with self.subTest(relationship=relationship):
                matrix = f"GPU2 GPU7\nGPU2 X {relationship}\nGPU7 {relationship} X\n"
                result, _ = self.inspect_matrix(matrix)
                self.assertEqual(result["status"], "OBSERVED")
                self.assertEqual(result["edges"][0]["relationship"], relationship)
                self.assertIsNone(result["edges"][0]["bandwidth_bytes_per_second"])
                self.assertEqual(result["affinities"], {"GPU-two": {}, "GPU-seven": {}})

    def test_single_gpu_has_no_manufactured_edge(self):
        identities = "7, GPU-seven\n"
        result, _ = self.inspect(
            [
                self.completed(identities),
                self.completed("GPU7\nGPU7 X\n"),
                self.completed(identities),
            ],
            devices=DEVICES[:1],
        )
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["edges"], [])
        self.assertTrue(
            any("no inter-device edges" in value for value in result["unknowns"])
        )

    def test_missing_executable_or_inventory_runs_no_command(self):
        result, run = self.inspect([], available=False)
        self.assertEqual(result["status"], "UNAVAILABLE")
        run.assert_not_called()
        for devices in ([], [{"index": 0}], [DEVICES[0], DEVICES[0]]):
            with self.subTest(devices=devices):
                result, run = self.inspect([], devices=devices)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["edges"], [])
                run.assert_not_called()

    def test_stale_or_remapped_inventory_stops_before_topology(self):
        for identity in (
            "2, GPU-seven\n7, GPU-two",
            "2, GPU-two",
            "2, GPU-two\n7, GPU-new",
        ):
            with self.subTest(identity=identity):
                result, run = self.inspect([self.completed(identity)])
                self.assertEqual(result["status"], "IDENTITY_CHANGED")
                self.assertEqual(result["edges"], [])
                self.assertEqual(run.call_count, 1)

    def test_changed_postmapping_discards_edges_and_preserves_raw(self):
        result, _ = self.inspect_matrix(MATRIX, after="2, GPU-seven\n7, GPU-two")
        self.assertEqual(result["status"], "IDENTITY_CHANGED")
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["raw"], MATRIX)
        self.assertNotIn("gpu_labels", result["evidence"])

    def test_malformed_identity_is_not_treated_as_verified(self):
        for invalid in (
            "",
            "2, GPU-two\n2, GPU-seven",
            "2, GPU-two\n7, GPU-two",
            "index, uuid",
            "2, GPU-two, extra",
        ):
            with self.subTest(invalid=invalid):
                result, _ = self.inspect_matrix(MATRIX, after=invalid)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["edges"], [])
                self.assertEqual(result["raw"], MATRIX)

    def test_missing_unknown_duplicate_and_malformed_matrix_labels_fail_safely(self):
        matrices = [
            "",
            "Topology not supported on this platform",
            "GPU2 GPU7 CPU Missing\nGPU2 X SYS\nGPU7 SYS X",
            "GPU2 GPU2\nGPU2 X SYS\nGPU2 SYS X",
            "GPU2 GPU0\nGPU2 X SYS\nGPU0 SYS X",
            "GPU2\nGPU2 X",
            "GPU2 GPU7\nGPU2 X SYS",
            "GPU2 GPU7\nGPU2 X SYS\nGPU2 SYS X",
            "GPU2 GPU7\nGPU2 X SYS\nGPU0 SYS X",
            "GPU2 GPU7\nGPU2 X NV#\nGPU7 NV# X",
            "GPU2 GPU7\nGPU2 X N/A\nGPU7 N/A X",
            "GPU2 GPU7\nGPU2 X SYS\nGPU7 PHB X",
            "GPU2 GPU7\nGPU2 X X\nGPU7 X X",
            "GPU2 GPU7\nGPU2 SYS SYS\nGPU7 SYS X",
            "GPU2 GPU7 NVME0\nGPU2 X SYS SYS\nGPU7 SYS X SYS\nNVME0 SYS SYS X",
        ]
        for matrix in matrices:
            with self.subTest(matrix=matrix):
                result, _ = self.inspect_matrix(matrix)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["edges"], [])
                self.assertEqual(result["raw"], matrix)

    def test_unsupported_command_preserves_output_and_error(self):
        result, _ = self.inspect(
            [
                self.completed(IDENTITIES),
                self.completed("Topology unavailable\n", "Not supported", 3),
                self.completed(IDENTITIES),
            ]
        )
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["raw"], "Topology unavailable\n")
        self.assertEqual(result["evidence"]["commands"][1]["stderr"], "Not supported")

    def test_process_timeouts_are_bounded_and_preserve_partial_matrix(self):
        for position in range(3):
            responses = [
                self.completed(IDENTITIES),
                self.completed(MATRIX),
                self.completed(IDENTITIES),
            ]
            responses[position] = subprocess.TimeoutExpired(
                "nvidia-smi",
                10 if position == 1 else 2,
                output=b"partial matrix",
                stderr=b"partial error",
            )
            with self.subTest(position=position):
                result, run = self.inspect(responses)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["edges"], [])
                self.assertEqual(run.call_count, 1 if position == 0 else 3)
                self.assertTrue(
                    any("TimeoutExpired" in value for value in result["unknowns"])
                )
                evidence = result["evidence"]["commands"][position]
                self.assertTrue(evidence["timed_out"])
                self.assertIsNone(evidence["returncode"])
                self.assertEqual(evidence["stdout"], "partial matrix")
                self.assertEqual(evidence["stderr"], "partial error")
                if position == 1:
                    self.assertEqual(result["raw"], "partial matrix")

    def test_timed_out_matrix_is_not_parsed_even_if_output_looks_complete(self):
        result, run = self.inspect(
            [
                self.completed(IDENTITIES),
                subprocess.TimeoutExpired("nvidia-smi", 10, output=MATRIX),
                self.completed(IDENTITIES),
            ]
        )
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["raw"], MATRIX)
        self.assertNotIn("gpu_labels", result["evidence"])
        self.assertEqual(run.call_count, 3)

    def test_process_execution_failure_is_explicit(self):
        result, run = self.inspect([OSError("executable disappeared")])
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["edges"], [])
        self.assertEqual(run.call_count, 1)
        self.assertTrue(
            any("executable disappeared" in value for value in result["unknowns"])
        )


if __name__ == "__main__":
    unittest.main()
