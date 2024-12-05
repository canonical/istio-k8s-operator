"""Configuration parser for the charm."""

from pydantic import BaseModel, Field


class CharmConfig(BaseModel):
    """Manager for the charm configuration."""

    ambient: bool
    platform: str = Field()  # type: ignore
    auto_allow_waypoint_policy: bool = Field(alias="auto-allow-waypoint-policy")  # type: ignore
