"""Hisense TV config flow."""
import json
from json.decoder import JSONDecodeError
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.const import CONF_MAC, CONF_NAME, CONF_PIN
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_MQTT_IN,
    CONF_MQTT_OUT,
    DEFAULT_CLIENT_ID,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class HisenseTvFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Hisense TV config flow."""

    VERSION = 1
    task_mqtt = None
    task_auth = None

    def __init__(self):
        """Initialize the config flow."""
        self._mac = None
        self._name = None
        self._mqtt_in = None
        self._mqtt_out = None
        self._unsubscribe_auth = None
        self._unsubscribe_sourcelist = None

    async def _async_pin_needed(self, message):
        _LOGGER.debug("_async_pin_needed")
        self._unsubscribe()
        self.task_auth = False
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )

    async def _async_pin_not_needed(self, message):
        _LOGGER.debug("_async_pin_not_needed")
        self._unsubscribe()
        self.task_auth = True
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )

    async def _async_authcode_response(self, message):
        self._unsubscribe()
        try:
            payload = json.loads(message.payload)
        except JSONDecodeError:
            payload = {}
        _LOGGER.debug("_async_authcode_respone %s", payload)
        self.task_auth = payload.get("result") == 1
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )

    def _unsubscribe(self):
        if self._unsubscribe_auth is not None:
            self._unsubscribe_auth()
            self._unsubscribe_auth = None
        if self._unsubscribe_sourcelist is not None:
            self._unsubscribe_sourcelist()
            self._unsubscribe_sourcelist = None

    async def async_step_user(self, user_input) -> FlowResult:
        if self.task_auth is True:
            return self.async_show_progress_done(next_step_id="finish")

        if self.task_auth is False:
            self.task_auth = None
            return self.async_show_progress_done(next_step_id="auth")

        if user_input is None:
            _LOGGER.debug("async_step_user INFO None")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                        vol.Required(CONF_MAC): str,
                        vol.Optional(CONF_MQTT_IN, default=DEFAULT_MQTT_PREFIX): str,
                        vol.Optional(CONF_MQTT_OUT, default=DEFAULT_MQTT_PREFIX): str,
                    }
                ),
            )

        _LOGGER.debug("async_step_user NOT task_mqtt")
        self.task_mqtt = {
            CONF_MAC: user_input.get(CONF_MAC),
            CONF_NAME: user_input.get(CONF_NAME),
            CONF_MQTT_IN: user_input.get(CONF_MQTT_IN),
            CONF_MQTT_OUT: user_input.get(CONF_MQTT_OUT),
        }

        await self._check_authentication(client_id=DEFAULT_CLIENT_ID)

        return self.async_show_progress(
            step_id="user",
            progress_action="progress_action",
        )

    async def _check_authentication(self, client_id):
        self._unsubscribe_auth = await mqtt.async_subscribe(
            hass=self.hass,
            topic="%s/remoteapp/mobile/%s/ui_service/data/authentication"
            % (self.task_mqtt.get(CONF_MQTT_IN), client_id),
            msg_callback=self._async_pin_needed,
        )
        self._unsubscribe_sourcelist = await mqtt.async_subscribe(
            hass=self.hass,
            topic="%s/remoteapp/mobile/%s/ui_service/data/sourcelist"
            % (self.task_mqtt.get(CONF_MQTT_IN), client_id),
            msg_callback=self._async_pin_not_needed,
        )
        mqtt.publish(
            hass=self.hass,
            topic="%s/remoteapp/tv/ui_service/%s/actions/gettvstate"
            % (self.task_mqtt.get(CONF_MQTT_OUT), client_id),
            payload="",
        )
        mqtt.publish(
            hass=self.hass,
            topic="%s/remoteapp/tv/ui_service/%s/actions/sourcelist"
            % (self.task_mqtt.get(CONF_MQTT_OUT), client_id),
            payload="",
        )

    async def async_step_reauth(self, user_input=None):
        """Reauth handler."""
        self.task_auth = None
        return await self.async_step_auth(user_input=user_input)

    async def async_step_auth(self, user_input=None):
        """Auth handler."""
        if self.task_auth is True:
            _LOGGER.debug("async_step_auth finish")
            return self.async_show_progress_done(next_step_id="finish")

        if self.task_auth is False:
            _LOGGER.debug("async_step_auth reauth")
            return self.async_show_progress_done(next_step_id="reauth")

        if user_input is None:
            self.task_auth = None
            _LOGGER.debug("async_step_auth show form")
            return self.async_show_form(
                step_id="auth",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_PIN): int,
                    }
                ),
            )
        else:
            _LOGGER.debug("async_step_auth send authentication")
            client_id = DEFAULT_CLIENT_ID
            self._unsubscribe_auth = await mqtt.async_subscribe(
                hass=self.hass,
                topic="%s/remoteapp/mobile/%s/ui_service/data/authenticationcode"
                % (self.task_mqtt.get(CONF_MQTT_IN), client_id),
                msg_callback=self._async_authcode_response,
            )
            payload = json.dumps({"authNum": user_input.get(CONF_PIN)})
            mqtt.publish(
                hass=self.hass,
                topic="%s/remoteapp/tv/ui_service/%s/actions/authenticationcode"
                % (self.task_mqtt.get(CONF_MQTT_OUT), client_id),
                payload=payload,
            )
            return self.async_show_progress(
                step_id="auth",
                progress_action="progress_action",
            )

    async def async_step_finish(self, user_input=None):
        """Finish config flow."""
        _LOGGER.debug("async_step_finish")
        return self.async_create_entry(title=self._name, data=self.task_mqtt)

    async def async_step_import(self, data):
        """Handle import from YAML."""
        _LOGGER.debug("async_step_import")
        return self.async_create_entry(title=data[CONF_NAME], data=data)

