import asyncio

from homeassistant.components import mqtt


async def mqtt_pub_sub(hass, pub, sub, payload=""):
    loop = asyncio.get_event_loop()
    queue = asyncio.Queue()

    def put(*args):
        loop.call_soon_threadsafe(queue.put_nowait, args)

    async def get():
        while True:
            yield await asyncio.wait_for(queue.get(), timeout=10)

    unsubscribe = await mqtt.async_subscribe(hass=hass, topic=sub, msg_callback=put)
    mqtt.async_publish(hass=hass, topic=pub, payload=payload)
    return get(), unsubscribe
