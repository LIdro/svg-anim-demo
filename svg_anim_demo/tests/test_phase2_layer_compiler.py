from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from svg_anim_demo.api import schemas
from svg_anim_demo.compiler.layer_compiler import LayerCompiler


SAMPLE_SVG = """
<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"320\" height=\"180\">
    <rect id=\"bg\" x=\"0\" y=\"0\" width=\"320\" height=\"180\" />
    <g id=\"title_group\" data-label=\"Hero Title\">
        <text id=\"title\" x=\"40\" y=\"60\" width=\"140\" height=\"30\">Highlife</text>
        <path d=\"M10 10 L20 20\" />
    </g>
    <circle cx=\"220\" cy=\"90\" r=\"24\" />
</svg>
""".strip()


class TestPhase2LayerCompiler(unittest.TestCase):
    @staticmethod
    def _validate(model_cls, payload):
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)

    def test_repeated_compile_produces_stable_ids(self):
        compiler = LayerCompiler()
        first = compiler.compile(SAMPLE_SVG)
        second = compiler.compile(SAMPLE_SVG)

        first_ids = [layer["id"] for layer in first.layer_map_full["layers"]]
        second_ids = [layer["id"] for layer in second.layer_map_full["layers"]]
        self.assertEqual(first_ids, second_ids)

    def test_maps_and_manifest_are_schema_valid(self):
        compiler = LayerCompiler()
        result = compiler.compile(SAMPLE_SVG)

        self._validate(schemas.LayerMapMinDocument, result.layer_map_min)
        self._validate(schemas.LayerMapFullDocument, result.layer_map_full)
        self._validate(schemas.CompileManifestDocument, result.compile_manifest)

    def test_manifest_changes_only_when_expected(self):
        compiler = LayerCompiler()

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            first = compiler.compile_to_directory(SAMPLE_SVG, out_dir)

            # unchanged source/version, manifest present => no recompile
            second = compiler.compile_to_directory(
                SAMPLE_SVG,
                out_dir,
                previous_manifest=first.compile_manifest,
            )
            self.assertFalse(second.recompile_required)
            self.assertEqual(second.compile_manifest, first.compile_manifest)

            # source change => recompile required
            changed_svg = SAMPLE_SVG.replace("Highlife", "Highlife 2")
            should_recompile, reason = compiler.needs_recompile(changed_svg, first.compile_manifest)
            self.assertTrue(should_recompile)
            self.assertEqual(reason, "source_checksum_changed")

            # compiler version change => recompile required
            newer_compiler = LayerCompiler(compiler_version="0.2.0")
            should_recompile, reason = newer_compiler.needs_recompile(SAMPLE_SVG, first.compile_manifest)
            self.assertTrue(should_recompile)
            self.assertEqual(reason, "compiler_version_changed")

            # manual recompile override
            should_recompile, reason = compiler.needs_recompile(
                SAMPLE_SVG,
                first.compile_manifest,
                manual_recompile=True,
            )
            self.assertTrue(should_recompile)
            self.assertEqual(reason, "manual_recompile")


if __name__ == "__main__":
    unittest.main()
