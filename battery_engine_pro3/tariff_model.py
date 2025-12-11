# battery_engine_pro3/tariff_model.py

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .types import TariffConfig, TariffCode, CountryCode


@dataclass
class TariffModel:
    """Abstraheert alle tarieflogica (NL en BE)."""
    config: TariffConfig

    def get_import_price(self, i: int, tariff: TariffCode) -> float:
        """
        Geeft importprijs per timestep en per tarief.
        Later voegen we logica toe voor dag/nacht en dynamische prijzen.
        """
        raise NotImplementedError("TariffModel.get_import_price is not implemented yet")

    def get_export_price(self, i: int, tariff: TariffCode) -> float:
        """
        Geeft exportprijs (feed-in) per timestep.
        """
        raise NotImplementedError("TariffModel.get_export_price is not implemented yet")

    def validate(self) -> None:
        """Basic sanity-checks op config."""
        # Hier kun je later extra validaties toevoegen.
        pass
