import asyncio
import logging
import voluptuous as vol
import wakeonlan
import json

from homeassistant.components import mqtt
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    BrowseMedia,
    PLATFORM_SCHEMA,
    DEVICE_CLASS_TV,
)
from homeassistant.components.media_player.const import (
    MEDIA_CLASS_APP,
    MEDIA_CLASS_DIRECTORY,
    MEDIA_CLASS_CHANNEL,
    MEDIA_TYPE_APP,
    MEDIA_TYPE_APPS,
    MEDIA_TYPE_CHANNEL,
    MEDIA_TYPE_TVSHOW,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_STEP,
    SUPPORT_VOLUME_SET,
    SUPPORT_BROWSE_MEDIA,
    SUPPORT_PLAY_MEDIA,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.config_entries import SOURCE_IMPORT

from .const import (
    CONF_MQTT_IN,
    CONF_MQTT_OUT,
    DOMAIN,
    DEFAULT_NAME,
    SERVICE_AUTHENTICATE,
    SERVICE_START_AUTHENTICATION,
    ATTR_CODE,
)
from .helper import mqtt_pub_sub

REQUIREMENTS = []

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_MQTT_IN): cv.string,
        vol.Required(CONF_MQTT_OUT): cv.string,
    }
)

AUTHENTICATE_SCHEMA = {
    vol.Required(ATTR_CODE): cv.Number,
}


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):

    if discovery_info:
        # Now handled by zeroconf in the config flow
        _LOGGER.debug("async_setup_platform with discovery_info")
        return

    mac = config[CONF_MAC]
    for entry in hass.config_entries.async_entries(DOMAIN):
        _LOGGER.debug("entry: %s" % entry.data)
        if entry.data[CONF_MAC] == mac:
            return

    entry_data = {
        CONF_NAME: config[CONF_NAME],
        CONF_MAC: config[CONF_MAC],
        CONF_MQTT_IN: config[CONF_MQTT_IN],
        CONF_MQTT_OUT: config[CONF_MQTT_OUT],
    }

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=entry_data
        )
    )


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the media player platform."""
    _LOGGER.debug("async_setup_entry config: %s" % config_entry.data)

    name = config_entry.data[CONF_NAME]
    mac = config_entry.data[CONF_MAC]
    mqtt_in = config_entry.data[CONF_MQTT_IN]
    mqtt_out = config_entry.data[CONF_MQTT_OUT]
    uid = config_entry.unique_id
    if uid is None:
        uid = config_entry.entry_id

    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
        SERVICE_START_AUTHENTICATION, {}, "async_start_authentication"
    )
    platform.async_register_entity_service(
        SERVICE_AUTHENTICATE, AUTHENTICATE_SCHEMA, "async_authenticate"
    )

    entity = HisenseTvEntity(
        hass=hass, name=name, mqtt_in=mqtt_in, mqtt_out=mqtt_out, mac=mac, uid=uid
    )
    async_add_entities([entity])


class HisenseTvEntity(MediaPlayerEntity):
    def __init__(
        self, hass, name: str, mqtt_in: str, mqtt_out: str, mac: str, uid: str
    ):
        self._client = "HomeAssistant"
        self._hass = hass
        self._name = name
        self._mqtt_in = mqtt_in or ""
        self._mqtt_out = mqtt_out or ""
        self._mac = mac
        self._unique_id = uid

        self._icon = "mdi:television-clear"
        self._muted = False
        self._volume = 0
        self._state = STATE_OFF
        self._source_name = None
        self._source_id = None
        self._source_list = {"App": {}}
        self._title = None
        self._channel_name = None
        self._channel_num = None
        self._channel_infos = {}
        self._app_list = {}
        self._subscriptions = {
            "tvsleep": lambda: None,
            "state": lambda: None,
            "volume": lambda: None,
            "sourcelist": lambda: None,
        }

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        _LOGGER.debug("media_content_type")
        # return MEDIA_TYPE_CHANNEL
        return MEDIA_TYPE_TVSHOW

    @property
    def device_class(self):
        """Set the device class to TV."""
        _LOGGER.debug("device_class")
        return DEVICE_CLASS_TV

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        return "hass:television-clean"

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        _LOGGER.debug("supported_features")
        return (
            SUPPORT_SELECT_SOURCE
            | SUPPORT_TURN_ON
            | SUPPORT_TURN_OFF
            | SUPPORT_VOLUME_MUTE
            | SUPPORT_VOLUME_STEP
            | SUPPORT_VOLUME_SET
            | SUPPORT_BROWSE_MEDIA
            | SUPPORT_PLAY_MEDIA
        )

    @property
    def unique_id(self):
        """Return the unique id of the device."""
        return self._unique_id

    @property
    def device_info(self):
        """Return device info for this device."""
        return {
            "identifiers": {(DOMAIN, self._unique_id)},
            "name": self._name,
            "manufacturer": DEFAULT_NAME,
        }

    @property
    def state(self):
        """Return the state of the device."""
        _LOGGER.debug("state %s" % self._state)
        return self._state

    def turn_on(self):
        """Turn the media player on."""
        _LOGGER.debug("turn_on")
        wakeonlan.send_magic_packet(self._mac)
        # self._state = STATE_OFF

    def turn_off(self):
        """Turn off media player."""
        _LOGGER.debug("turn_off")
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/remote_service/%s/actions/sendkey"),
            payload="KEY_POWER",
            retain=False,
        )
        # self._state = STATE_OFF

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        _LOGGER.debug("is_volume_muted %s" % self._muted)
        return self._muted

    @property
    def volume_level(self):
        """Volume level of the media player (0..100)."""
        _LOGGER.debug("volume_level %d" % self._volume)
        return self._volume / 100

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        _LOGGER.debug("set_volume_level %s" % volume)
        self._volume = int(volume * 100)
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic(
                "/remoteapp/tv/platform_service/%s/actions/changevolume"
            ),
            payload=self._volume,
        )

    def volume_up(self):
        """Volume up the media player."""
        _LOGGER.debug("volume_up")
        if self._volume < 100:
            self._volume = self._volume + 1
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/remote_service/%s/actions/sendkey"),
            payload="KEY_VOLUMEUP",
        )

    def volume_down(self):
        """Volume down media player."""
        _LOGGER.debug("volume_down")
        if self._volume > 0:
            self._volume = self._volume - 1
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/remote_service/%s/actions/sendkey"),
            payload="KEY_VOLUMEDOWN",
        )

    def mute_volume(self, mute):
        """Send mute command."""
        _LOGGER.debug("mute_volume %s" % mute)
        self._muted = mute
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/remote_service/%s/actions/sendkey"),
            payload="KEY_MUTE",
        )

    @property
    def source_list(self):
        """List of available input sources."""
        _LOGGER.debug("source_list")
        return sorted(list(self._source_list))

    @property
    def source(self):
        """Return the current input source."""
        _LOGGER.debug("source")
        return self._source_name

    @property
    def media_title(self):
        """Return the title of current playing media."""
        if self._state == STATE_OFF:
            return None

        _LOGGER.debug("media_title %s", self._title)
        return self._title

    @property
    def media_series_title(self):
        """Return the channel current playing media."""
        if self._state == STATE_OFF:
            return None

        if self._channel_num != None:
            channel = "%s (%s)" % (self._channel_name, self._channel_num)
        else:
            channel = self._channel_name
        _LOGGER.debug("media_series_title %s" % channel)
        return channel

    async def async_select_source(self, source):
        """Select input source."""
        _LOGGER.debug("async_select_source %s" % source)

        if source == "App":
            mqtt.async_publish(
                hass=self._hass,
                topic=self._out_topic(
                    "/remoteapp/tv/remote_service/%s/actions/sendkey"
                ),
                payload="KEY_HOME",
            )
            return

        source_dic = self._source_list.get(source)
        payload = json.dumps({"sourceid": source_dic.get("sourceid")})
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/ui_service/%s/actions/changesource"),
            payload=payload,
        )

    def _check_state(self):
        _LOGGER.debug("_check_state: %s", self._state)
        if self._state == STATE_ON:
            _LOGGER.debug("_check_state skip")
            return

        _LOGGER.debug("_check_state publish")
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/ui_service/%s/actions/gettvstate"),
            payload="0",
        )

    async def async_will_remove_from_hass(self):
        for unsubscribe in list(self._subscriptions.values()):
            unsubscribe()

    async def async_added_to_hass(self):
        """Subscribe to MQTT events."""
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
            self._message_received_volume,
        )

        self._subscriptions["sourcelist"] = await mqtt.async_subscribe(
            self._hass,
            self._out_topic("/remoteapp/mobile/%s/ui_service/data/sourcelist"),
            self._message_received_sourcelist,
        )

    def _out_topic(self, topic=""):
        try:
            out_topic = self._mqtt_out + topic % self._client
        except:
            out_topic = self._mqtt_out + topic % self._client
        _LOGGER.debug("_out_topic: %s" % out_topic)
        return out_topic

    def _in_topic(self, topic=""):
        try:
            in_topic = self._mqtt_in + topic % self._client
        except:
            in_topic = self._mqtt_in + topic
        _LOGGER.debug("_in_topic: %s" % in_topic)
        return in_topic

    async def _message_received_turnoff(self, msg):
        """Run when new MQTT message has been received."""
        _LOGGER.debug("message_received_turnoff")
        self._state = STATE_OFF
        self.async_write_ha_state()

    async def _message_received_sourcelist(self, msg):
        """Run when new MQTT message has been received."""
        self._check_state()
        payload = json.loads(msg.payload)
        self._source_list = {s.get("sourcename"): s for s in payload}
        self._source_list["App"] = {}
        _LOGGER.debug("message_received_sourcelist R(%s):\n%s" % (msg.retain, payload))

    async def _message_received_volume(self, msg):
        """Run when new MQTT message has been received."""
        self._check_state()
        _LOGGER.debug("message_received_volume R(%s)\n%s" % (msg.retain, msg.payload))
        payload = json.loads(msg.payload)
        if payload.get("volume_type") == 0:
            self._volume = payload.get("volume_value")
        elif payload.get("volume_type") == 2:
            self._muted = payload.get("volume_value") == 1
        self.async_write_ha_state()

    async def _message_received_state(self, msg):
        """Run when new MQTT message has been received."""
        if msg.retain == True:
            _LOGGER.debug("message_received_state - skip retained message")
            return

        payload = json.loads(msg.payload)
        statetype = payload.get("statetype")
        _LOGGER.debug("message_received_state %s" % statetype)

        if self._state == STATE_OFF:
            mqtt.async_publish(
                hass=self._hass,
                topic=self._out_topic(
                    "/remoteapp/tv/platform_service/%s/actions/getvolume"
                ),
                payload="",
            )
            mqtt.async_publish(
                hass=self._hass,
                topic=self._out_topic("/remoteapp/tv/ui_service/%s/actions/sourcelist"),
                payload="",
            )

        if statetype == "sourceswitch":
            # sourceid:
            # sourcename:
            # is_signal:
            # displayname:
            self._source_name = payload.get("sourcename")
            self._source_id = payload.get("sourceid")
            self._title = payload.get("displayname")
            self._channel_name = payload.get("sourcename")
            self._channel_num = None
        elif statetype == "livetv":
            # progname:
            # channel_num:
            # channel_name:
            # sourceid:
            # detail:
            # starttime:
            # endtime:
            self._source_name = "TV"
            self._title = payload.get("progname")
            self._channel_name = payload.get("channel_name")
            self._channel_num = payload.get("channel_num")
        elif statetype == "remote_launcher":
            self._source_name = "App"
            self._title = "Applications"
            self._channel_name = None
            self._channel_num = None
        elif statetype == "app":
            # name:
            # url:
            self._source_name = "App"
            self._title = payload.get("name")
            self._channel_name = payload.get("url")
            self._channel_num = None
        elif statetype == "remote_epg":
            pass

        self._state = STATE_ON
        self.async_write_ha_state()

    async def _build_library_node(self):
        node = BrowseMedia(
            title="Media Library",
            media_class=MEDIA_CLASS_DIRECTORY,
            media_content_type="library",
            media_content_id="library",
            can_play=False,
            can_expand=True,
            children=[],
        )

        stream_get, unsubscribe_getchannellistinfo = await mqtt_pub_sub(
            hass=self._hass,
            pub=self._out_topic(
                "/remoteapp/tv/platform_service/%s/actions/getchannellistinfo"
            ),
            sub=self._in_topic(
                "/remoteapp/mobile/%s/platform_service/data/getchannellistinfo"
            ),
        )

        try:
            async for msg in stream_get:
                payload = json.loads(msg[0].payload)
                self._channel_infos = {item.get("list_para"): item for item in payload}
                for key, item in self._channel_infos.items():
                    node.children.append(
                        BrowseMedia(
                            title=item.get("list_name"),
                            media_class=MEDIA_CLASS_DIRECTORY,
                            media_content_type="channellistinfo",
                            media_content_id=key,
                            can_play=False,
                            can_expand=True,
                        )
                    )
                break
        except asyncio.TimeoutError:
            _LOGGER.debug("timeout error - getchannellistinfo")
            pass

        node.children.append(
            BrowseMedia(
                title="Applications",
                media_class=MEDIA_CLASS_APP,
                media_content_type=MEDIA_TYPE_APPS,
                media_content_id="app_list",
                can_play=False,
                can_expand=True,
            )
        )
        unsubscribe_getchannellistinfo()
        return node

    async def _build_app_list_node(self):
        node = BrowseMedia(
            title="Applications",
            media_class=MEDIA_CLASS_APP,
            media_content_type=MEDIA_TYPE_APPS,
            media_content_id="app_list",
            can_play=False,
            can_expand=True,
            children=[],
        )

        stream_get, unsubscribe_applist = await mqtt_pub_sub(
            hass=self._hass,
            pub=self._out_topic("/remoteapp/tv/ui_service/%s/actions/applist"),
            sub=self._in_topic("/remoteapp/mobile/%s/ui_service/data/applist"),
        )

        try:
            async for msg in stream_get:
                payload = json.loads(msg[0].payload)
                self._app_list = {item.get("appId"): item for item in payload}
                for id, item in self._app_list.items():
                    node.children.append(
                        BrowseMedia(
                            title=item.get("name"),
                            media_class=MEDIA_CLASS_APP,
                            media_content_type=MEDIA_TYPE_APP,
                            media_content_id=id,
                            can_play=True,
                            can_expand=False,
                        )
                    )
                break
        except asyncio.TimeoutError:
            _LOGGER.debug("timeout error - applist")
            pass

        unsubscribe_applist()
        return node

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        """Implement the websocket media browsing helper."""

        if media_content_id in [None, "library"]:
            return await self._build_library_node()
        elif media_content_id == "app_list":
            return await self._build_app_list_node()

        list_name = self._channel_infos.get(media_content_id).get("list_name")
        node = BrowseMedia(
            title=list_name,
            media_class=MEDIA_CLASS_DIRECTORY,
            media_content_type="channellistinfo",
            media_content_id=media_content_id,
            can_play=False,
            can_expand=True,
            children=[],
        )

        channel_info = json.dumps(
            {"list_para": media_content_id, "list_name": list_name}
        )
        stream_get, unsubscribe_channellist = await mqtt_pub_sub(
            hass=self._hass,
            pub=self._out_topic(
                "/remoteapp/tv/platform_service/%s/actions/channellist"
            ),
            sub=self._in_topic(
                "/remoteapp/mobile/%s/platform_service/data/channellist"
            ),
            payload=channel_info,
        )

        try:
            async for msg in stream_get:
                payload = json.loads(msg[0].payload)
                for item in payload.get("list"):
                    node.children.append(
                        BrowseMedia(
                            title=item.get("channel_name"),
                            media_class=MEDIA_CLASS_CHANNEL,
                            media_content_type=MEDIA_TYPE_CHANNEL,
                            media_content_id=item.get("channel_param"),
                            can_play=True,
                            can_expand=False,
                        )
                    )
                break
        except asyncio.TimeoutError:
            _LOGGER.debug("timeout error - channellist")
            pass

        unsubscribe_channellist()
        return node

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Send the play_media command to the media player."""
        _LOGGER.debug("async_play_media %s\n%s" % (media_id, kwargs))

        if media_type == MEDIA_TYPE_CHANNEL:
            channel = json.dumps({"channel_param": media_id})
            mqtt.async_publish(
                hass=self._hass,
                topic=self._out_topic(
                    "/remoteapp/tv/ui_service/%s/actions/changechannel"
                ),
                payload=channel,
            )
        elif media_type == MEDIA_CLASS_APP:
            app = self._app_list.get(media_id)
            payload = json.dumps(
                {"appId": media_id, "name": app.get("name"), "url": app.get("url")}
            )
            mqtt.async_publish(
                hass=self._hass,
                topic=self._out_topic("/remoteapp/tv/ui_service/%s/actions/launchapp"),
                payload=payload,
            )

    async def async_start_authentication(self):
        _LOGGER.debug("async_start_authentication")
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic("/remoteapp/tv/ui_service/%s/actions/gettvstate"),
            payload="",
        )

    async def async_authenticate(self, auth_code):
        _LOGGER.debug("async_authenticate: %s" % auth_code)
        payload = json.dumps({"authNum": auth_code})
        mqtt.async_publish(
            hass=self._hass,
            topic=self._out_topic(
                "/remoteapp/tv/ui_service/%s/actions/authenticationcode"
            ),
            payload=payload,
        )
