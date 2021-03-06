"""Support for Velbus devices."""
import asyncio
import logging
import velbus
import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_PORT, CONF_NAME
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import HomeAssistantType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

VELBUS_MESSAGE = "velbus.message"

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.Schema({vol.Required(CONF_PORT): cv.string})}, extra=vol.ALLOW_EXTRA
)

COMPONENT_TYPES = ["switch", "sensor", "binary_sensor", "cover", "climate"]


async def async_setup(hass, config):
    """Set up the Velbus platform."""
    # Import from the configuration file if needed
    if DOMAIN not in config:
        return True

    port = config[DOMAIN].get(CONF_PORT)
    data = {}

    if port:
        data = {CONF_PORT: port, CONF_NAME: "Velbus import"}

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=data
        )
    )

    return True


async def async_setup_entry(hass: HomeAssistantType, entry: ConfigEntry):
    """Establish connection with velbus."""
    hass.data.setdefault(DOMAIN, {})

    def callback():
        modules = controller.get_modules()
        discovery_info = {"cntrl": controller}
        for category in COMPONENT_TYPES:
            discovery_info[category] = []

        for module in modules:
            for channel in range(1, module.number_of_channels() + 1):
                for category in COMPONENT_TYPES:
                    if category in module.get_categories(channel):
                        discovery_info[category].append(
                            (module.get_module_address(), channel)
                        )

        hass.data[DOMAIN][entry.entry_id] = discovery_info

        for category in COMPONENT_TYPES:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, category)
            )

    try:
        controller = velbus.Controller(entry.data[CONF_PORT])
        controller.scan(callback)
    except velbus.util.VelbusException as err:
        _LOGGER.error("An error occurred: %s", err)
        raise ConfigEntryNotReady

    def syn_clock(self, service=None):
        try:
            controller.sync_clock()
        except velbus.util.VelbusException as err:
            _LOGGER.error("An error occurred: %s", err)

    hass.services.async_register(DOMAIN, "sync_clock", syn_clock, schema=vol.Schema({}))

    return True


async def async_unload_entry(hass: HomeAssistantType, entry: ConfigEntry):
    """Remove the velbus connection."""
    await asyncio.wait(
        [
            hass.config_entries.async_forward_entry_unload(entry, component)
            for component in COMPONENT_TYPES
        ]
    )
    hass.data[DOMAIN][entry.entry_id]["cntrl"].stop()
    hass.data[DOMAIN].pop(entry.entry_id)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True


class VelbusEntity(Entity):
    """Representation of a Velbus entity."""

    def __init__(self, module, channel):
        """Initialize a Velbus entity."""
        self._module = module
        self._channel = channel

    @property
    def unique_id(self):
        """Get unique ID."""
        serial = 0
        if self._module.serial == 0:
            serial = self._module.get_module_address()
        else:
            serial = self._module.serial
        return f"{serial}-{self._channel}"

    @property
    def name(self):
        """Return the display name of this entity."""
        return self._module.get_name(self._channel)

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    async def async_added_to_hass(self):
        """Add listener for state changes."""
        self._module.on_status_update(self._channel, self._on_update)

    def _on_update(self, state):
        self.schedule_update_ha_state()

    @property
    def device_info(self):
        """Return the device info."""
        return {
            "identifiers": {
                (DOMAIN, self._module.get_module_address(), self._module.serial)
            },
            "name": "{} {}".format(
                self._module.get_module_address(), self._module.get_module_name()
            ),
            "manufacturer": "Velleman",
            "model": self._module.get_module_name(),
            "sw_version": "{}.{}-{}".format(
                self._module.memory_map_version,
                self._module.build_year,
                self._module.build_week,
            ),
        }
