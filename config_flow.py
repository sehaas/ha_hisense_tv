from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_MAC
from homeassistant.components import mqtt
from .const import DOMAIN, CONF_MQTT_IN, CONF_MQTT_OUT

import voluptuous as vol
import logging

_LOGGER = logging.getLogger(__name__)


class HisenseTvFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Example config flow."""

    def __init__(self):
        """Initialize the config flow."""
        self._mac = None
        self._name = None
        self._mqtt_in = None
        self._mqtt_out = None

    async def async_step_user(self, info):
        if info is not None:
            self._mac = info.get(CONF_MAC)
            self._name = info.get(CONF_NAME)
            self._mqtt_in = info.get(CONF_MQTT_IN)
            self._mqtt_out = info.get(CONF_MQTT_OUT)
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_MAC: self._mac,
                    CONF_NAME: self._name,
                    CONF_MQTT_IN: self._mqtt_in,
                    CONF_MQTT_OUT: self._mqtt_out,
                },
            )

        default_mqtt_in = self._mqtt_in or "hisense"
        default_mqtt_out = self._mqtt_out or "hisense"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Required(CONF_NAME, default=self._name): str,
                    vol.Optional(CONF_MQTT_IN, default=default_mqtt_in): str,
                    vol.Optional(CONF_MQTT_OUT, default=default_mqtt_out): str,
                }
            ),
        )

    async def async_step_import(self, data):
        """Handle import from YAML."""
        _LOGGER.warn("async_step_import")
        return self.async_create_entry(title=data[CONF_NAME], data=data)
