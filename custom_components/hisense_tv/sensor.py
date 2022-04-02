"""Support for Picture Settings sensors."""
from datetime import timedelta
import json
from json.decoder import JSONDecodeError
import logging
from wakeonlan import BROADCAST_IP

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_NAME
from homeassistant.util import dt as dt_util

from .const import CONF_MQTT_IN, CONF_MQTT_OUT, DEFAULT_NAME, DOMAIN
from .helper import HisenseTvBase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up MQTT sensors dynamically through MQTT discovery."""
    _LOGGER.debug("async_setup_entry config: %s", config_entry.data)

    name = config_entry.data[CONF_NAME]
    mac = config_entry.data[CONF_MAC]
    ip_address = config_entry.data.get(CONF_IP_ADDRESS, BROADCAST_IP)
    mqtt_in = config_entry.data[CONF_MQTT_IN]
    mqtt_out = config_entry.data[CONF_MQTT_OUT]
    uid = config_entry.unique_id
    if uid is None:
        uid = config_entry.entry_id

    entity = HisenseTvSensor(
        hass=hass,
        name=name,
        mqtt_in=mqtt_in,
        mqtt_out=mqtt_out,
        mac=mac,
        uid=uid,
        ip_address=ip_address,
    )
    async_add_entities([entity])


class HisenseTvSensor(SensorEntity, HisenseTvBase):
    """Representation of a sensor that can be updated using MQTT."""

    def __init__(self, hass, name, mqtt_in, mqtt_out, mac, uid, ip_address):
        HisenseTvBase.__init__(
            self=self,
            hass=hass,
            name=name,
            mqtt_in=mqtt_in,
            mqtt_out=mqtt_out,
            mac=mac,
            uid=uid,
            ip_address=ip_address,
        )
        self._is_available = False
        self._state = {}
        self._last_trigger = dt_util.utcnow()
        self._force_trigger = False

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
            self._message_received_turnon,
        )

        self._subscriptions["picturesettings"] = await mqtt.async_subscribe(
            self._hass,
            self._in_topic("/remoteapp/mobile/%s/platform_service/data/picturesetting"),
            self._message_received,
        )

        self._subscriptions["picturesettings_value"] = await mqtt.async_subscribe(
            self._hass,
            self._in_topic(
                "/remoteapp/mobile/broadcast/platform_service/data/picturesetting"
            ),
            self._message_received_value,
        )

    async def _message_received_turnoff(self, msg):
        _LOGGER.debug("message_received_turnoff")
        self._is_available = False
        self.async_write_ha_state()

    async def _message_received_turnon(self, msg):
        _LOGGER.debug("message_received_turnon")
        if msg.retain:
            _LOGGER.debug("message_received_turnon - skip retained message")
            return

        self._is_available = True
        self._force_trigger = True
        self.async_write_ha_state()

    async def _message_received(self, msg):
        self._is_available = True
        try:
            payload = json.loads(msg.payload)
        except JSONDecodeError:
            payload = {}
        _LOGGER.debug("_message_received R(%s):\n%s", msg.retain, payload)
        self._state = {
            s.get("menu_id"): {"name": s.get("menu_name"), "value": s.get("menu_value")}
            for s in payload.get("menu_info", [])
        }
        self.async_write_ha_state()

    async def _message_received_value(self, msg):
        self._is_available = True
        self._force_trigger = True
        try:
            payload = json.loads(msg.payload)
        except JSONDecodeError:
            payload = {}
        _LOGGER.debug("_message_received_value R(%s):\n%s", msg.retain, payload)
        if "notify_value_changed" == payload.get("action"):
            menu_id = payload.get("menu_id")
            entry = self._state.get(menu_id)
            if entry is not None:
                entry["value"] = payload.get("menu_value")
            else:
                _LOGGER.debug("_message_received_value menu_id not found: %s", menu_id)

        self.async_write_ha_state()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state.get(91, {}).get("value", "")

    @property
    def available(self):
        """Return True if entity is available."""
        return self._is_available

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return self._icon

    @property
    def extra_state_attributes(self):
        """Return the state attributes of the sensor."""
        return {v["name"]: v["value"] for k, v in self._state.items()}

    async def async_update(self):
        """Get the latest data and updates the states."""
        if (
            not self._force_trigger
            and dt_util.utcnow() - self._last_trigger < timedelta(minutes=5)
        ):
            _LOGGER.debug("Skip update")
            return

        _LOGGER.debug("Update. force=%s", self._force_trigger)
        self._force_trigger = False
        self._last_trigger = dt_util.utcnow()

        await mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic(
                "/remoteapp/tv/platform_service/%s/actions/picturesetting"
            ),
            payload='{"action": "get_menu_info"}',
            retain=False,
        )

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
