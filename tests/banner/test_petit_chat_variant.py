from __future__ import annotations

import pytest

from vibe.cli.textual_ui.widgets.banner.petit_chat import CatVariant


class TestCatVariantFromModel:
    @pytest.mark.parametrize(
        "model",
        [
            "ml4",
            "Mistral Large 4",
            "mistral-large-latest",
            "mistral-large-4",
            "mistral-large-4-0",
            "le-chaton-fat",
            "le-gros-chaton",
            "le-chonk",
        ],
    )
    def test_large_models_pick_lechonk(self, model: str) -> None:
        assert CatVariant.from_model(model) is CatVariant.LECHONK

    @pytest.mark.parametrize(
        "model", ["mistral-medium-latest", "magistral-medium-latest", "test-model", ""]
    )
    def test_other_models_pick_lechat(self, model: str) -> None:
        assert CatVariant.from_model(model) is CatVariant.LECHAT
