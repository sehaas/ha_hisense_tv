"""Hisense TV switch entity"""
import logging

import wakeonlan

from homeassistant.components import mqtt
from homeassistant.components.switch import DEVICE_CLASS_SWITCH, SwitchEntity
from homeassistant.const import CONF_MAC, CONF_NAME

from .const import CONF_MQTT_IN, CONF_MQTT_OUT, DEFAULT_NAME, DOMAIN
from .helper import HisenseTvBase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Start HisenseTV switch setup process."""
    _LOGGER.debug("async_setup_entry config: %s", config_entry.data)

    name = config_entry.data[CONF_NAME]
    mac = config_entry.data[CONF_MAC]
    mqtt_in = config_entry.data[CONF_MQTT_IN]
    mqtt_out = config_entry.data[CONF_MQTT_OUT]
    uid = config_entry.unique_id
    if uid is None:
        uid = config_entry.entry_id

    entity = HisenseTvSwitch(
        hass=hass, name=name, mqtt_in=mqtt_in, mqtt_out=mqtt_out, mac=mac, uid=uid
    )
    async_add_entities([entity])


class HisenseTvSwitch(SwitchEntity, HisenseTvBase):
    """Hisense TV switch entity."""

    def __init__(self, hass, name, mqtt_in, mqtt_out, mac, uid):
        HisenseTvBase.__init__(
            self=self,
            hass=hass,
            name=name,
            mqtt_in=mqtt_in,
            mqtt_out=mqtt_out,
            mac=mac,
            uid=uid,
        )
        self._is_on = False

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        wakeonlan.send_magic_packet(self._mac)

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        await mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/remote_service/%s/actions/sendkey"),
            payload="KEY_POWER",
            retain=False,
        )

    @property
    def is_on(self):
        return self._is_on

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._name,
            "manufacturer": DEFAULT_NAME,
        }

    @property
    def unique_id(self):
        """Return the unique id of the device."""
        return self._unique_id

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        return self._icon

    @property
    def device_class(self):
        _LOGGER.debug("device_class")
        return DEVICE_CLASS_SWITCH

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    async def async_will_remove_from_hass(self):
        for unsubscribe in list(self._subscriptions.values()):
            unsubscribe()

    async def async_added_to_hass(self):
        self._subscriptions["tvsleep"] = await mqtt.async_subscribe(
            self._hass,
            self._in_topic(
                "/remoteapp/mobile/broadcast/platform_service/actions/tvsleep"
            ),
            self._message_received_turnoff,
        )

        self._subscriptions["state"] = await mqtt.async_subscribe(
            self._hass,
            self._in_topic("/remoteapp/mobile/broadcast/ui_service/state"),
            self._message_received_state,
        )

        self._subscriptions["volume"] = await mqtt.async_subscribe(
            self._hass,
            self._in_topic(
                "/remoteapp/mobile/broadcast/platform_service/actions/volumechange"
            ),
            self._message_received_state,
        )

        self._subscriptions["sourcelist"] = await mqtt.async_subscribe(
            self._hass,
            self._out_topic("/remoteapp/mobile/%s/ui_service/data/sourcelist"),
            self._message_received_state,
        )

    async def _message_received_turnoff(self, msg):
        _LOGGER.debug("message_received_turnoff")
        self._is_on = False
        self.async_write_ha_state()

    async def _message_received_state(self, msg):
        if msg.retain is True:
            _LOGGER.debug("SWITCH message_received_state - skip retained message")
            return

        _LOGGER.debug("SWITCH message_received_state - turn on")
        self._is_on = True
        self.async_write_ha_state()
