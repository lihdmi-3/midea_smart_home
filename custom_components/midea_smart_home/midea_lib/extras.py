"""Midea Smart Home Extra Logic Handler."""

import logging
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

T0xD9_POLL_ATTRIBUTES = [
    "db_detergent_needed",
    "db_remain_time",
    "db_progress",
    "db_running_status",
    "db_error_code",
]


class DeviceLogicHandler:
    def __init__(self, device_type: int, device_name: str):
        self.device_type = device_type
        self.device_name = device_name
        self._last_standby_status: Any = None
        self._poll_mode: bool = False
        self._current_db_running_status: Optional[str] = None
        self._current_db_running_status_l: Optional[str] = None
        self._current_db_running_status_r: Optional[str] = None

    def set_poll_mode(self, enabled: bool) -> None:
        self._poll_mode = enabled

    @property
    def poll_mode(self) -> bool:
        return self._poll_mode

    def filter_report_data(self, data: dict) -> dict:
        if self.device_type != 0xD9:
            return data

        if not self._poll_mode:
            return data

        db_position = data.get("db_position")
        if db_position == 1:
            return data

        _LOGGER.debug(
            "[%s] T0xD9 filter_report_data: db_position=%s, data filtered out",
            self.device_name,
            db_position
        )
        return {}

    def process_poll_data(
        self,
        data: dict,
        query_location: Optional[int] = None
    ) -> dict:
        if self.device_type != 0xD9:
            return data

        if not data:
            return {}

        if not self._poll_mode:
            return data

        if query_location is None:
            query_location = data.get("db_location")

        if not self.validate_poll_response(data, query_location):
            _LOGGER.debug(
                "[%s] T0xD9 process_poll_data: db_location mismatch, query=%s, response=%s",
                self.device_name,
                query_location,
                data.get("db_location")
            )
            return {}

        suffix = "_l" if query_location == 1 else "_r" if query_location == 2 else ""
        if not suffix:
            return data

        result = {}
        for key, value in data.items():
            if key in T0xD9_POLL_ATTRIBUTES:
                new_key = f"{key}{suffix}"
                result[new_key] = value
            else:
                result[key] = value

        _LOGGER.debug(
            "[%s] T0xD9 process_poll_data: query_location=%s, suffix=%s, result=%s",
            self.device_name,
            query_location,
            suffix,
            result
        )
        return result

    def validate_poll_response(self, data: dict, query_location: Optional[int]) -> bool:
        if self.device_type != 0xD9:
            return True

        if query_location is None:
            return True

        response_location = data.get("db_location")
        if response_location is None:
            return True

        return response_location == query_location

    def validate_running_status_transition(
        self,
        new_status: Optional[str],
        current_status: Optional[str]
    ) -> bool:
        if new_status is None:
            return True

        if new_status != "end":
            return True

        if current_status == "start":
            return True

        _LOGGER.debug(
            "[%s] T0xD9 validate_running_status_transition: invalid transition from %s to end",
            self.device_name,
            current_status
        )
        return False

    def validate_running_status_with_progress(
        self,
        data: dict,
        running_status_key: str = "db_running_status",
        progress_key: str = "db_progress"
    ) -> bool:
        running_status = data.get(running_status_key)
        if running_status != "end":
            return True

        progress = data.get(progress_key)
        if progress is None:
            return True

        try:
            if isinstance(progress, str):
                progress_value = int(progress, 16) if progress.startswith("0x") else int(progress)
            else:
                progress_value = int(progress)

            if progress_value != 0:
                _LOGGER.debug(
                    "[%s] T0xD9 validate_running_status_with_progress: running_status=end but progress=%s",
                    self.device_name,
                    progress
                )
                return False
        except (ValueError, TypeError):
            pass

        return True

    def update_db_running_status(
        self,
        data: dict,
        current_data: Optional[dict] = None
    ) -> Optional[str]:
        if self.device_type != 0xD9:
            return None

        db_position = data.get("db_position")
        if db_position != 1:
            _LOGGER.debug(
                "[%s] T0xD9 update_db_running_status: db_position=%s, not updating",
                self.device_name,
                db_position
            )
            return None

        db_running_status = data.get("db_running_status")
        if db_running_status is None:
            return None

        if not self.validate_running_status_with_progress(data):
            _LOGGER.debug(
                "[%s] T0xD9 update_db_running_status: progress validation failed",
                self.device_name
            )
            return None

        current_status = None
        if current_data:
            current_status = current_data.get("db_running_status")

        if not self.validate_running_status_transition(db_running_status, current_status):
            _LOGGER.debug(
                "[%s] T0xD9 update_db_running_status: transition validation failed",
                self.device_name
            )
            return None

        self._current_db_running_status = db_running_status
        _LOGGER.debug(
            "[%s] T0xD9 update_db_running_status: updated to %s",
            self.device_name,
            db_running_status
        )
        return db_running_status

    def update_db_running_status_with_suffix(
        self,
        data: dict,
        suffix: str,
        current_data: Optional[dict] = None
    ) -> Optional[str]:
        if self.device_type != 0xD9:
            return None

        db_position = data.get("db_position")
        if db_position != 1:
            return None

        running_status_key = f"db_running_status{suffix}"
        progress_key = f"db_progress{suffix}"

        db_running_status = data.get(running_status_key)
        if db_running_status is None:
            return None

        temp_data = {
            running_status_key: db_running_status,
            progress_key: data.get(progress_key)
        }

        if not self.validate_running_status_with_progress(temp_data, running_status_key, progress_key):
            return None

        current_status = None
        if current_data:
            current_status = current_data.get(running_status_key)

        if not self.validate_running_status_transition(db_running_status, current_status):
            return None

        if suffix == "_l":
            self._current_db_running_status_l = db_running_status
        elif suffix == "_r":
            self._current_db_running_status_r = db_running_status

        return db_running_status

    def adjust_control_status(self, data: dict, running_status: str) -> None:
        control_status = "start" if running_status == "start" else "pause"
        control_status_key = "db_control_status" if self.device_type == 0xD9 else "control_status"
        data[control_status_key] = control_status

    def adjust_work_switch(self, data: dict) -> None:
        if "work_status" in data:
            work_status = data["work_status"]
            if work_status == "cancel":
                data["work_switch"] = 0
            elif work_status in ("cooking", "keep_warm"):
                data["work_switch"] = 2

    def adjust_ac_mode(self, data: dict) -> None:
        if "mode" in data:
            power = data.get("power")
            if power == "off" or power == 0:
                data["mode"] = "idle"

    def apply_special_handling(
        self,
        data: dict,
        recent_controls: dict,
        control_timeout: float,
        is_control: bool = False,
        control_attrs: dict = None,
        is_poll: bool = False,
        query_location: Optional[int] = None,
        current_data: Optional[dict] = None
    ) -> None:
        if self.device_type == 0xD9:
            if is_poll:
                self._apply_t0xd9_poll_handling(data, query_location, current_data)
            else:
                self._apply_t0xd9_report_handling(data, current_data)

        elif self.device_type in [0xDA, 0xDB, 0xDC]:
            if "running_status" in data:
                self.adjust_control_status(data, data["running_status"])
            self.process_progress(data, "running_status", "progress")
            self._adjust_remain_time(data)

        elif self.device_type == 0xEA:
            self.adjust_work_switch(data)

        elif self.device_type == 0xAC:
            self.adjust_ac_mode(data)

        elif self.device_type == 0xED:
            self.adjust_standby_status_for_wash(data)

    def _apply_t0xd9_report_handling(
        self,
        data: dict,
        current_data: Optional[dict] = None
    ) -> None:
        if self._poll_mode:
            filtered_data = self.filter_report_data(data)
            if not filtered_data:
                data.clear()
                return

        if "db_running_status" in data:
            self.adjust_control_status(data, data["db_running_status"])
        self.process_progress(data, "db_running_status", "db_progress")
        self._adjust_db_running_status_for_power_off(data)
        self._adjust_db_remain_time(data)

    def _apply_t0xd9_poll_handling(
        self,
        data: dict,
        query_location: Optional[int],
        current_data: Optional[dict]
    ) -> None:
        processed_data = self.process_poll_data(data, query_location)
        if not processed_data:
            data.clear()
            return

        data.clear()
        data.update(processed_data)

        suffix = "_l" if query_location == 1 else "_r" if query_location == 2 else ""
        if suffix:
            self._apply_t0xd9_suffixed_attributes_handling(data, suffix, current_data)

        if query_location == 1:
            db_position = data.get("db_position")
            if db_position == 1:
                running_status_key = f"db_running_status{suffix}"
                progress_key = f"db_progress{suffix}"
                temp_data = {
                    "db_running_status": data.get(running_status_key),
                    "db_progress": data.get(progress_key),
                    "db_position": db_position
                }

                if self.validate_running_status_with_progress(temp_data):
                    current_status = current_data.get("db_running_status") if current_data else None
                    if self.validate_running_status_transition(temp_data.get("db_running_status"), current_status):
                        if running_status_key in data:
                            data["db_running_status"] = data[running_status_key]
                            self.adjust_control_status(data, data["db_running_status"])

    def _apply_t0xd9_suffixed_attributes_handling(
        self,
        data: dict,
        suffix: str,
        current_data: Optional[dict] = None
    ) -> None:
        running_status_key = f"db_running_status{suffix}"
        progress_key = f"db_progress{suffix}"
        remain_time_key = f"db_remain_time{suffix}"

        self._adjust_db_running_status_for_power_off(data, running_status_key)

        self._adjust_db_remain_time_with_key(data, remain_time_key, running_status_key)

        self.process_progress(data, running_status_key, progress_key)

    def _adjust_db_running_status_for_power_off(
        self,
        data: dict,
        status_key: str = "db_running_status"
    ) -> None:
        db_power = data.get("db_power")
        if db_power == "off" or db_power == 0:
            if status_key in data:
                data[status_key] = "standby"

    def _adjust_remain_time(self, data: dict) -> None:
        if "remain_time" not in data or "running_status" not in data:
            return
        running_status = data["running_status"]
        if running_status == "start":
            return
        elif running_status == "end":
            data["remain_time"] = 0
        else:
            data["remain_time"] = None

    def _adjust_db_remain_time(self, data: dict) -> None:
        self._adjust_db_remain_time_with_key(data, "db_remain_time", "db_running_status")

    def _adjust_db_remain_time_with_key(
        self,
        data: dict,
        remain_time_key: str,
        running_status_key: str
    ) -> None:
        if remain_time_key not in data or running_status_key not in data:
            return
        running_status = data[running_status_key]
        if running_status == "start":
            return
        elif running_status == "end":
            data[remain_time_key] = 0
        else:
            data[remain_time_key] = None

    def process_progress(self, data: dict, status_key: str, progress_key: str) -> None:
        """Process progress sensor special logic"""
        if progress_key not in data:
            return

        running_status = data.get(status_key)
        if running_status != "start":
            data[progress_key] = "idle"
            return

        value = data[progress_key]
        try:
            if isinstance(value, str):
                value = int(value, 16) if value.startswith("0x") else int(value)

            calculated_value = 0
            if value > 0:
                calculated_value = (value & -value).bit_length()
        except (ValueError, TypeError):
            if isinstance(value, str):
                return
            calculated_value = -1

        if self.device_type == 0xDA:
            progress_map = {
                0: "idle",
                1: "spin",
                2: "rinse",
                3: "wash",
                4: "weight",
                5: "unknown",
                6: "dry",
                7: "soak",
            }
        elif self.device_type == 0xDC:
            progress_map = {
                0: "idle",
                1: "dry",
                2: "anti-wrinkle",
                3: "cold_air",
            }
        else:
            progress_map = {
                0: "idle",
                1: "spin",
                2: "rinse",
                3: "wash",
                4: "pre-wash",
                5: "dry",
                6: "weight",
                7: "spin_high",
                8: "unknown",
            }
        data[progress_key] = progress_map.get(calculated_value, "unknown")

    def prepare_control_data(self, control: dict, current_data: dict = None) -> dict:
        """Prepare control data with device-specific requirements."""
        if self.device_type == 0xD9:
            control["bucket"] = "db"
            if "db_location" not in control and current_data and "db_location" in current_data:
                control["db_location"] = current_data["db_location"]
        return control

    def adjust_standby_status_for_wash(self, data: dict) -> None:
        """For T0xED devices, prevent standby_status update when wash is on."""
        if self.device_type != 0xED:
            return

        if "standby_status" not in data or "wash" not in data:
            return

        wash_status = data.get("wash")
        if wash_status == "on" or wash_status == 1:
            if self._last_standby_status is not None:
                data["standby_status"] = self._last_standby_status
        else:
            self._last_standby_status = data.get("standby_status")
