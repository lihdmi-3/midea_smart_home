import asyncio
import logging
from typing import Any, Union

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .midea_lib.device import MideaDevice

_LOGGER = logging.getLogger(__name__)

StatusDict = dict[str, Union[str, int, float, bool, None]]
ControlValue = Union[str, int, float, bool, None]


class MideaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Midea Smart Home devices.

    This class bridges Home Assistant and the MideaDevice library.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device: MideaDevice,
        device_name: str,
        poll_interval: int = 1,
        poll_query: dict | None = None,
        poll_attributes: list | None = None,
    ):
        self.device = device
        self.device_name = device_name
        self.device_type = device.device_id
        self.poll_interval = poll_interval
        self.poll_query = poll_query
        self.poll_attributes = poll_attributes
        self._poll_task: asyncio.Task | None = None
        self._poll_enabled = bool(poll_query and poll_attributes)

        super().__init__(
            hass,
            _LOGGER,
            name=f"Midea Smart Home {device_name}",
            update_interval=None,
        )

        device.register_update(self._device_update_callback)

    @property
    def controller(self):
        """Return the device controller."""
        return self.device.controller

    def _device_update_callback(self) -> None:
        """Handle device data updates."""
        if not self.hass or self.hass.is_stopping:
            return

        if self.device.available:
            self._start_polling()
        else:
            self._stop_polling()

        self.hass.loop.call_soon_threadsafe(
            self.async_set_updated_data, self.device.data
        )

    def _start_polling(self) -> None:
        """Start the polling task if poll_query and poll_attributes are configured."""
        if not self._poll_enabled:
            return

        if self._poll_task is not None and not self._poll_task.done():
            return

        self._poll_task = asyncio.create_task(self._async_poll_data())
        _LOGGER.debug(
            "[%s] Started polling with interval %s seconds",
            self.device_name,
            self.poll_interval
        )

    def _stop_polling(self) -> None:
        """Stop the polling task."""
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            _LOGGER.debug("[%s] Stopped polling", self.device_name)
        self._poll_task = None

    async def _async_poll_data(self) -> None:
        """Periodically poll device status."""
        while True:
            try:
                await asyncio.sleep(self.poll_interval)
                if self.device.available:
                    await self.hass.async_add_executor_job(
                        self.device.refresh_status, self.poll_query
                    )
            except asyncio.CancelledError:
                _LOGGER.debug("[%s] Polling task cancelled", self.device_name)
                break
            except Exception as e:
                _LOGGER.error("[%s] Error during polling: %s", self.device_name, e)

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the current data."""
        return self.device.data or {}

    async def async_set_control(
        self,
        attr: str | dict,
        value: ControlValue = None
    ) -> StatusDict:
        """Send control command to the device."""
        if isinstance(attr, dict):
            await self.hass.async_add_executor_job(self.device.set_attributes, attr)
        else:
            await self.hass.async_add_executor_job(self.device.set_attribute, attr, value)

        return self.device.data

    async def async_set_controls(self, controls: dict[str, ControlValue]) -> StatusDict:
        """Send multiple control commands."""
        return await self.async_set_control(controls)
