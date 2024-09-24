"""Configuration parser for the charm."""

from pydantic import BaseModel, Field


class CharmConfig(BaseModel):
    """Manager for the charm configuration."""

    ambient: bool
    cni_bin_dir: str = Field(alias="cni-bin-dir")
    cni_conf_dir: str = Field(alias="cni-conf-dir")
    auto_allow_waypoint_policy: bool = Field(alias="auto-allow-waypoint-policy")
