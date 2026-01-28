"""Configuration parser for the charm."""

from pydantic import BaseModel, Field


class CharmConfig(BaseModel):
    """Manager for the charm configuration."""

    platform: str = Field()  # type: ignore
    cniBinDir: str = Field()  # noqa: N815 (Mixed Case)
    cniConfDir: str = Field()  # noqa: N815 (Mixed Case)
    auto_allow_waypoint_policy: bool = Field(alias="auto-allow-waypoint-policy")  # type: ignore
    hardened_mode: bool = Field(alias="hardened-mode")  # type: ignore
