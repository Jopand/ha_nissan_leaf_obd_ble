"""Vehicle generation profiles for Nissan Leaf OBD commands.

This module defines generation-specific command configurations for different
Nissan Leaf generations (ZE0, AZE0, ZE1).

Supported generations:
  - auto: Automatic mode (default) - includes both odometer sources for maximum compatibility
  - ze0: 2010-2017 Nissan Leaf (original)
  - aze0: 2017-2018 Nissan Leaf (minor refresh)
  - ze1: 2018+ Nissan Leaf (major redesign, currently ZE1 platform)

Each profile specifies:
  - which commands to enable/disable
  - any command-specific overrides
  - generation-specific quirks

When a generation is selected via async_get_data(generation="ze1"),
the API will apply the appropriate profile's overrides to the default
command table.

The "auto" profile is recommended for existing integrations as it ensures
backwards compatibility by including both active and passive odometer sources.
Users can optionally specify their vehicle generation for optimized command sets.
"""

import logging
from typing import Optional

from .commands import leaf_commands
from .OBDCommand import OBDCommand

logger = logging.getLogger(__name__)


# ZE1 (2018+) - Optimized profile for newest generation
# Uses ReadDataByIdentifier for the odometer on header 0x743
# Has full suite of modern ECU diagnostics
PROFILE_ZE1 = {
    "name": "ZE1 (2018+)",
    "description": "2018 and later Nissan Leaf (ZE1 platform, optimized profile)",
    "disabled_commands": {"odometer_can"},  # Use active diagnostics instead
    "extra_commands": {},
}

# ZE0/AZE0 (2010-2018) - Optimized profiles for original and refreshed generations
# Uses passive CAN broadcast 0x5C5 instead of active diagnostics
# May have different or missing PIDs on some ECUs
PROFILE_ZE0 = {
    "name": "ZE0 (2010-2017)",
    "description": "2010-2017 Nissan Leaf (ZE0 platform, optimized profile)",
    "disabled_commands": {"odometer"},  # Use passive CAN broadcast instead
    "extra_commands": {},
}

PROFILE_AZE0 = {
    "name": "AZE0 (2017-2018)",
    "description": "2017-2018 Nissan Leaf (AZE0 platform, optimized profile)",
    "disabled_commands": {"odometer"},  # Use passive CAN broadcast instead
    "extra_commands": {},
}

# AUTO (Default) - Backwards compatible mode
# Includes both active and passive odometer sources for maximum compatibility
# ZE0/AZE0 users: active query fails -> passive works ✓
# ZE1 users: active query works -> passive is redundant but harmless ✓
PROFILE_AUTO = {
    "name": "Auto (All Generations)",
    "description": "Automatic mode for maximum compatibility - includes both odometer sources",
    "disabled_commands": set(),  # No commands disabled, get both odometer sources
    "extra_commands": {},
}

# Map of generation names to profiles
PROFILES = {
    "auto": PROFILE_AUTO,
    "ze0": PROFILE_ZE0,
    "aze0": PROFILE_AZE0,
    "ze1": PROFILE_ZE1,
}

# Default generation if not specified
# "auto" provides maximum compatibility by including both odometer sources
DEFAULT_GENERATION = "auto"

VALID_GENERATIONS = set(PROFILES.keys())


def get_profile(generation: str) -> dict:
    """Get the profile configuration for a given generation.
    
    Args:
        generation: One of 'ze0', 'aze0', or 'ze1'
        
    Returns:
        Profile dict with 'name', 'description', 'disabled_commands', and 'extra_commands'
        
    Raises:
        ValueError: if generation is not recognized
    """
    if generation not in PROFILES:
        raise ValueError(
            f"Unknown generation '{generation}'. "
            f"Valid options: {', '.join(sorted(VALID_GENERATIONS))}"
        )
    return PROFILES[generation]


def get_generation_commands(
    generation: str,
    extra_commands: Optional[dict] = None,
    disabled_commands: Optional[set] = None,
) -> dict:
    """Get the complete command table for a given generation.
    
    This applies generation-specific profiles and then user-provided overrides.
    Order of precedence (highest to lowest):
      1. User-provided disabled_commands (skipped entirely)
      2. User-provided extra_commands (override everything)
      3. Profile-specific extra_commands (override defaults)
      4. Profile-specific disabled_commands (removed from defaults)
      5. Default leaf_commands
    
    Args:
        generation: One of 'ze0', 'aze0', or 'ze1'
        extra_commands: User-provided command overrides
        disabled_commands: User-provided commands to disable
        
    Returns:
        dict[str, OBDCommand] for the given generation with overrides applied
    """
    profile = get_profile(generation)
    
    # Start with defaults
    commands = dict(leaf_commands)
    
    # Apply profile-specific disabled commands
    for cmd_name in profile.get("disabled_commands", set()):
        commands.pop(cmd_name, None)
    
    # Apply profile-specific overrides
    profile_extra = profile.get("extra_commands", {})
    if profile_extra:
        commands.update(profile_extra)
    
    # Apply user-specific disabled commands
    user_disabled = disabled_commands or set()
    for cmd_name in user_disabled:
        commands.pop(cmd_name, None)
    
    # Apply user-specific overrides (highest precedence)
    user_extra = extra_commands or {}
    if user_extra:
        commands.update(user_extra)
    
    logger.debug(
        "Generated command table for generation %s with %d commands",
        generation,
        len(commands),
    )
    
    return commands
