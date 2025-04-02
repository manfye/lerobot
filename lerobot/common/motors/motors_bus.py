#!/usr/bin/env python

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ruff: noqa: N802
# This noqa is for the Protocols classes: PortHandler, PacketHandler GroupSyncRead/Write
# TODO(aliberts): Add block noqa when feature below is available
# https://github.com/astral-sh/ruff/issues/3711

import abc
import logging
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from pprint import pformat
from typing import Protocol, TypeAlias, overload

import serial
from deepdiff import DeepDiff
from tqdm import tqdm

from lerobot.common.errors import DeviceAlreadyConnectedError, DeviceNotConnectedError
from lerobot.common.utils.utils import enter_pressed, move_cursor_up

NameOrID: TypeAlias = str | int
Value: TypeAlias = int | float

MAX_ID_RANGE = 252

logger = logging.getLogger(__name__)


def get_ctrl_table(model_ctrl_table: dict[str, dict], model: str) -> dict[str, tuple[int, int]]:
    ctrl_table = model_ctrl_table.get(model)
    if ctrl_table is None:
        raise KeyError(f"Control table for {model=} not found.")
    return ctrl_table


def get_address(model_ctrl_table: dict[str, dict], model: str, data_name: str) -> tuple[int, int]:
    ctrl_table = get_ctrl_table(model_ctrl_table, model)
    addr_bytes = ctrl_table.get(data_name)
    if addr_bytes is None:
        raise KeyError(f"Address for '{data_name}' not found in {model} control table.")
    return addr_bytes


def assert_same_address(model_ctrl_table: dict[str, dict], motor_models: list[str], data_name: str) -> None:
    all_addr = []
    all_bytes = []
    for model in motor_models:
        addr, bytes = get_address(model_ctrl_table, model, data_name)
        all_addr.append(addr)
        all_bytes.append(bytes)

    if len(set(all_addr)) != 1:
        raise NotImplementedError(
            f"At least two motor models use a different address for `data_name`='{data_name}'"
            f"({list(zip(motor_models, all_addr, strict=False))})."
        )

    if len(set(all_bytes)) != 1:
        raise NotImplementedError(
            f"At least two motor models use a different bytes representation for `data_name`='{data_name}'"
            f"({list(zip(motor_models, all_bytes, strict=False))})."
        )


class MotorNormMode(Enum):
    DEGREE = 0
    RANGE_0_100 = 1
    RANGE_M100_100 = 2
    VELOCITY = 3


@dataclass
class MotorCalibration:
    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int


@dataclass
class Motor:
    id: int
    model: str
    norm_mode: MotorNormMode


class JointOutOfRangeError(Exception):
    def __init__(self, message="Joint is out of range"):
        self.message = message
        super().__init__(self.message)


class PortHandler(Protocol):
    def __init__(self, port_name):
        self.is_open: bool
        self.baudrate: int
        self.packet_start_time: float
        self.packet_timeout: float
        self.tx_time_per_byte: float
        self.is_using: bool
        self.port_name: str
        self.ser: serial.Serial

    def openPort(self): ...
    def closePort(self): ...
    def clearPort(self): ...
    def setPortName(self, port_name): ...
    def getPortName(self): ...
    def setBaudRate(self, baudrate): ...
    def getBaudRate(self): ...
    def getBytesAvailable(self): ...
    def readPort(self, length): ...
    def writePort(self, packet): ...
    def setPacketTimeout(self, packet_length): ...
    def setPacketTimeoutMillis(self, msec): ...
    def isPacketTimeout(self): ...
    def getCurrentTime(self): ...
    def getTimeSinceStart(self): ...
    def setupPort(self, cflag_baud): ...
    def getCFlagBaud(self, baudrate): ...


class PacketHandler(Protocol):
    def getTxRxResult(self, result): ...
    def getRxPacketError(self, error): ...
    def txPacket(self, port, txpacket): ...
    def rxPacket(self, port): ...
    def txRxPacket(self, port, txpacket): ...
    def ping(self, port, id): ...
    def action(self, port, id): ...
    def readTx(self, port, id, address, length): ...
    def readRx(self, port, id, length): ...
    def readTxRx(self, port, id, address, length): ...
    def read1ByteTx(self, port, id, address): ...
    def read1ByteRx(self, port, id): ...
    def read1ByteTxRx(self, port, id, address): ...
    def read2ByteTx(self, port, id, address): ...
    def read2ByteRx(self, port, id): ...
    def read2ByteTxRx(self, port, id, address): ...
    def read4ByteTx(self, port, id, address): ...
    def read4ByteRx(self, port, id): ...
    def read4ByteTxRx(self, port, id, address): ...
    def writeTxOnly(self, port, id, address, length, data): ...
    def writeTxRx(self, port, id, address, length, data): ...
    def write1ByteTxOnly(self, port, id, address, data): ...
    def write1ByteTxRx(self, port, id, address, data): ...
    def write2ByteTxOnly(self, port, id, address, data): ...
    def write2ByteTxRx(self, port, id, address, data): ...
    def write4ByteTxOnly(self, port, id, address, data): ...
    def write4ByteTxRx(self, port, id, address, data): ...
    def regWriteTxOnly(self, port, id, address, length, data): ...
    def regWriteTxRx(self, port, id, address, length, data): ...
    def syncReadTx(self, port, start_address, data_length, param, param_length): ...
    def syncWriteTxOnly(self, port, start_address, data_length, param, param_length): ...


class GroupSyncRead(Protocol):
    def __init__(self, port, ph, start_address, data_length):
        self.port: str
        self.ph: PortHandler
        self.start_address: int
        self.data_length: int
        self.last_result: bool
        self.is_param_changed: bool
        self.param: list
        self.data_dict: dict

    def makeParam(self): ...
    def addParam(self, id): ...
    def removeParam(self, id): ...
    def clearParam(self): ...
    def txPacket(self): ...
    def rxPacket(self): ...
    def txRxPacket(self): ...
    def isAvailable(self, id, address, data_length): ...
    def getData(self, id, address, data_length): ...


class GroupSyncWrite(Protocol):
    def __init__(self, port, ph, start_address, data_length):
        self.port: str
        self.ph: PortHandler
        self.start_address: int
        self.data_length: int
        self.is_param_changed: bool
        self.param: list
        self.data_dict: dict

    def makeParam(self): ...
    def addParam(self, id, data): ...
    def removeParam(self, id): ...
    def changeParam(self, id, data): ...
    def clearParam(self): ...
    def txPacket(self): ...


class MotorsBus(abc.ABC):
    """The main LeRobot class for implementing motors buses.

    There are currently two implementations of this abstract class:
        - DynamixelMotorsBus
        - FeetechMotorsBus

    Note: This class may evolve in the future should we add support for other manufacturers SDKs.

    A MotorsBus allows to efficiently read and write to the attached motors.
    It represents several motors daisy-chained together and connected through a serial port.

    A MotorsBus subclass instance requires a port (e.g. `FeetechMotorsBus(port="/dev/tty.usbmodem575E0031751"`)).
    To find the port, you can run our utility script:
    ```bash
    python lerobot/scripts/find_motors_bus_port.py
    >>> Finding all available ports for the MotorsBus.
    >>> ['/dev/tty.usbmodem575E0032081', '/dev/tty.usbmodem575E0031751']
    >>> Remove the usb cable from your MotorsBus and press Enter when done.
    >>> The port of this MotorsBus is /dev/tty.usbmodem575E0031751.
    >>> Reconnect the usb cable.
    ```

    Example of usage for 1 Feetech sts3215 motor connected to the bus:
    ```python
    motors_bus = FeetechMotorsBus(
        port="/dev/tty.usbmodem575E0031751",
        motors={"gripper": (6, "sts3215")},
    )
    motors_bus.connect()

    position = motors_bus.read("Present_Position")

    # Move from a few motor steps as an example
    few_steps = 30
    motors_bus.write("Goal_Position", position + few_steps)

    # When done, properly disconnect the port using
    motors_bus.disconnect()
    ```
    """

    available_baudrates: list[int]
    default_timeout: int
    model_baudrate_table: dict[str, dict]
    model_ctrl_table: dict[str, dict]
    model_number_table: dict[str, int]
    model_resolution_table: dict[str, int]
    normalization_required: list[str]

    def __init__(
        self,
        port: str,
        motors: dict[str, Motor],
        calibration: dict[str, MotorCalibration] | None = None,
    ):
        self.port = port
        self.motors = motors
        self.calibration = calibration if calibration else {}

        self.port_handler: PortHandler
        self.packet_handler: PacketHandler
        self.sync_reader: GroupSyncRead
        self.sync_writer: GroupSyncWrite
        self._comm_success: int
        self._no_error: int

        self._id_to_model_dict = {m.id: m.model for m in self.motors.values()}
        self._id_to_name_dict = {m.id: name for name, m in self.motors.items()}
        self._model_nb_to_model_dict = {v: k for k, v in self.model_number_table.items()}

    def __len__(self):
        return len(self.motors)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(\n"
            f"    Port: '{self.port}',\n"
            f"    Motors: \n{pformat(self.motors, indent=8, sort_dicts=False)},\n"
            ")',\n"
        )

    @cached_property
    def _has_different_ctrl_tables(self) -> bool:
        if len(self.models) < 2:
            return False

        first_table = self.model_ctrl_table[self.models[0]]
        return any(
            DeepDiff(first_table, get_ctrl_table(self.model_ctrl_table, model)) for model in self.models[1:]
        )

    @cached_property
    def names(self) -> list[str]:
        return list(self.motors)

    @cached_property
    def models(self) -> list[str]:
        return [m.model for m in self.motors.values()]

    @cached_property
    def ids(self) -> list[int]:
        return [m.id for m in self.motors.values()]

    def _model_nb_to_model(self, motor_nb: int) -> str:
        return self._model_nb_to_model_dict[motor_nb]

    def _id_to_model(self, motor_id: int) -> str:
        return self._id_to_model_dict[motor_id]

    def _id_to_name(self, motor_id: int) -> str:
        return self._id_to_name_dict[motor_id]

    def _get_motor_id(self, motor: NameOrID) -> int:
        if isinstance(motor, str):
            return self.motors[motor].id
        elif isinstance(motor, int):
            return motor
        else:
            raise TypeError(f"'{motor}' should be int, str.")

    def _get_motor_model(self, motor: NameOrID) -> int:
        if isinstance(motor, str):
            return self.motors[motor].model
        elif isinstance(motor, int):
            return self._id_to_model_dict[motor]
        else:
            raise TypeError(f"'{motor}' should be int, str.")

    def _validate_motors(self) -> None:
        if len(self.ids) != len(set(self.ids)):
            raise ValueError(f"Some motors have the same id!\n{self}")

        # Ensure ctrl table available for all models
        for model in self.models:
            get_ctrl_table(self.model_ctrl_table, model)

    def _is_comm_success(self, comm: int) -> bool:
        return comm == self._comm_success

    def _is_error(self, error: int) -> bool:
        return error != self._no_error

    def _assert_motors_exist(self) -> None:
        # TODO(aliberts): collect all wrong ids/models and display them at once
        found_models = self.broadcast_ping()
        expected_models = {m.id: self.model_number_table[m.model] for m in self.motors.values()}
        if not found_models or set(found_models) != set(self.ids):
            raise RuntimeError(
                f"{self.__class__.__name__} is supposed to have these motors: ({{id: model_nb}})"
                f"\n{pformat(expected_models, indent=4, sort_dicts=False)}\n"
                f"But it found these motors on port '{self.port}':"
                f"\n{pformat(found_models, indent=4, sort_dicts=False)}\n"
            )

        for id_, model in expected_models.items():
            if found_models[id_] != model:
                raise RuntimeError(
                    f"Motor '{self._id_to_name(id_)}' (id={id_}) is supposed to be of model_number={model} "
                    f"('{self._id_to_model(id_)}') but a model_number={found_models[id_]} "
                    "was found instead for that id."
                )

    @property
    def is_connected(self) -> bool:
        return self.port_handler.is_open

    def connect(self, assert_motors_exist: bool = True) -> None:
        if self.is_connected:
            raise DeviceAlreadyConnectedError(
                f"{self.__class__.__name__}('{self.port}') is already connected. Do not call `{self.__class__.__name__}.connect()` twice."
            )

        try:
            if not self.port_handler.openPort():
                raise OSError(f"Failed to open port '{self.port}'.")
            elif assert_motors_exist:
                self._assert_motors_exist()
        except (FileNotFoundError, OSError, serial.SerialException) as e:
            raise ConnectionError(
                f"\nCould not connect on port '{self.port}'. Make sure you are using the correct port."
                "\nTry running `python lerobot/scripts/find_motors_bus_port.py`\n"
            ) from e

        self.set_timeout()
        logger.debug(f"{self.__class__.__name__} connected.")

    @classmethod
    def scan_port(cls, port: str) -> dict[int, list[int]]:
        bus = cls(port, {})
        try:
            bus.port_handler.openPort()
        except (FileNotFoundError, OSError, serial.SerialException) as e:
            raise ConnectionError(
                f"Could not connect to port '{port}'. Make sure you are using the correct port."
                "\nTry running `python lerobot/scripts/find_motors_bus_port.py`\n"
            ) from e
        baudrate_ids = {}
        for baudrate in tqdm(bus.available_baudrates, desc="Scanning port"):
            bus.set_baudrate(baudrate)
            ids_models = bus.broadcast_ping()
            if ids_models:
                tqdm.write(f"Motors found for {baudrate=}: {pformat(ids_models, indent=4)}")
                baudrate_ids[baudrate] = list(ids_models)

        return baudrate_ids

    @abc.abstractmethod
    def configure_motors(self) -> None:
        pass

    def disable_torque(self, motors: NameOrID | list[NameOrID] | None = None) -> None:
        pass
        if motors is None:
            motors = self.names
        elif isinstance(motors, (str, int)):
            motors = [motors]
        elif not isinstance(motors, list):
            raise TypeError(motors)

        self._disable_torque(motors)

    def enable_torque(self, motors: NameOrID | list[NameOrID] | None = None) -> None:
        pass
        if motors is None:
            motors = self.names
        elif isinstance(motors, (str, int)):
            motors = [motors]
        elif not isinstance(motors, list):
            raise TypeError(motors)

        self._enable_torque(motors)

    @abc.abstractmethod
    def _enable_torque(self, motors: list[NameOrID]) -> None:
        pass

    @abc.abstractmethod
    def _disable_torque(self, motors: list[NameOrID]) -> None:
        pass

    def set_timeout(self, timeout_ms: int | None = None):
        timeout_ms = timeout_ms if timeout_ms is not None else self.default_timeout
        self.port_handler.setPacketTimeoutMillis(timeout_ms)

    def get_baudrate(self) -> int:
        return self.port_handler.getBaudRate()

    def set_baudrate(self, baudrate: int) -> None:
        present_bus_baudrate = self.port_handler.getBaudRate()
        if present_bus_baudrate != baudrate:
            logger.info(f"Setting bus baud rate to {baudrate}. Previously {present_bus_baudrate}.")
            self.port_handler.setBaudRate(baudrate)

            if self.port_handler.getBaudRate() != baudrate:
                raise OSError("Failed to write bus baud rate.")

    def reset_calibration(self, motors: NameOrID | list[NameOrID] | None = None) -> None:
        if motors is None:
            motors = self.names
        elif isinstance(motors, (str, int)):
            motors = [motors]
        elif not isinstance(motors, list):
            raise TypeError(motors)

        for motor in motors:
            model = self._get_motor_model(motor)
            max_res = self.model_resolution_table[model] - 1
            self.write("Homing_Offset", motor, 0, normalize=False)
            self.write("Min_Position_Limit", motor, 0, normalize=False)
            self.write("Max_Position_Limit", motor, max_res, normalize=False)

    @property
    def is_calibrated(self) -> bool:
        return self.calibration == self.read_calibration()

    def read_calibration(self) -> dict[str, MotorCalibration]:
        offsets = self.sync_read("Homing_Offset", normalize=False)
        mins = self.sync_read("Min_Position_Limit", normalize=False)
        maxes = self.sync_read("Max_Position_Limit", normalize=False)

        try:
            drive_modes = self.sync_read("Drive_Mode", normalize=False)
        except KeyError:
            drive_modes = {name: 0 for name in self.names}

        calibration = {}
        for name, motor in self.motors.items():
            calibration[name] = MotorCalibration(
                id=motor.id,
                drive_mode=drive_modes[name],
                homing_offset=offsets[name],
                range_min=mins[name],
                range_max=maxes[name],
            )

        return calibration

    def write_calibration(self, calibration_dict: dict[str, MotorCalibration]) -> None:
        for motor, calibration in calibration_dict.items():
            self.write("Homing_Offset", motor, calibration.homing_offset)
            self.write("Min_Position_Limit", motor, calibration.range_min)
            self.write("Max_Position_Limit", motor, calibration.range_max)

        self.calibration = calibration_dict

    def set_half_turn_homings(self, motors: NameOrID | list[NameOrID] | None = None) -> dict[NameOrID, Value]:
        """This assumes motors present positions are roughly in the middle of their desired range"""
        if motors is None:
            motors = self.names
        elif isinstance(motors, (str, int)):
            motors = [motors]
        else:
            raise TypeError(motors)

        # Step 1: Set homing and min max to 0
        self.reset_calibration(motors)

        # Step 2: Read Present_Position which will be Actual_Position since
        # Present_Position = Actual_Position ± Homing_Offset (1)
        # and Homing_Offset = 0 from step 1
        actual_positions = self.sync_read("Present_Position", motors, normalize=False)

        # Step 3: We want to set the Homing_Offset such that the current Present_Position to be half range of
        # 1 revolution.
        # For instance, if 1 revolution corresponds to 4095 (4096 steps), this means we want the current
        # Present_Position to be 2047. In that example:
        # Present_Position = 2047 (2)
        # Actual_Position = X (read in step 2)
        # from (1) and (2):
        # => Homing_Offset = ±(X - 2048)
        homing_offsets = self._get_half_turn_homings(actual_positions)
        for motor, offset in homing_offsets.items():
            self.write("Homing_Offset", motor, offset)

        return homing_offsets

    def record_ranges_of_motion(
        self, motors: NameOrID | list[NameOrID] | None = None, display_values: bool = True
    ) -> tuple[dict[NameOrID, Value], dict[NameOrID, Value]]:
        """
        This assumes that the homing offsets have been set such that all possible values in the range of
        motion are positive and that the zero is not crossed. To that end, `set_half_turn_homings` should
        typically be called prior to this.
        """
        if motors is None:
            motors = self.names
        elif isinstance(motors, (str, int)):
            motors = [motors]
        elif not isinstance(motors, list):
            raise TypeError(motors)

        start_positions = self.sync_read("Present_Position", motors, normalize=False)
        mins = start_positions.copy()
        maxes = start_positions.copy()
        while True:
            positions = self.sync_read("Present_Position", motors, normalize=False)
            mins = {motor: min(positions[motor], min_) for motor, min_ in mins.items()}
            maxes = {motor: max(positions[motor], max_) for motor, max_ in maxes.items()}

            if display_values:
                print("\n-------------------------------------------")
                print(f"{'NAME':<15} | {'MIN':>6} | {'POS':>6} | {'MAX':>6}")
                for name in motors:
                    print(f"{name:<15} | {mins[name]:>6} | {positions[name]:>6} | {maxes[name]:>6}")

            if enter_pressed():
                break

            if display_values:
                # Move cursor up to overwrite the previous output
                move_cursor_up(len(motors) + 3)

        return mins, maxes

    @abc.abstractmethod
    def _get_half_turn_homings(self, positions: dict[NameOrID, Value]) -> dict[NameOrID, Value]:
        pass

    def _normalize(self, data_name: str, ids_values: dict[int, int]) -> dict[int, float]:
        normalized_values = {}
        for id_, val in ids_values.items():
            name = self._id_to_name(id_)
            min_ = self.calibration[name].range_min
            max_ = self.calibration[name].range_max
            bounded_val = min(max_, max(min_, val))
            if self.motors[name].norm_mode is MotorNormMode.RANGE_M100_100:
                normalized_values[id_] = (((bounded_val - min_) / (max_ - min_)) * 200) - 100
            elif self.motors[name].norm_mode is MotorNormMode.RANGE_0_100:
                normalized_values[id_] = ((bounded_val - min_) / (max_ - min_)) * 100
            else:
                # TODO(alibers): velocity and degree modes
                raise NotImplementedError

        return normalized_values

    def _unnormalize(self, data_name: str, ids_values: dict[int, float]) -> dict[int, int]:
        unnormalized_values = {}
        for id_, val in ids_values.items():
            name = self._id_to_name(id_)
            min_ = self.calibration[name].range_min
            max_ = self.calibration[name].range_max
            if self.motors[name].norm_mode is MotorNormMode.RANGE_M100_100:
                bounded_val = min(100.0, max(-100.0, val))
                unnormalized_values[id_] = int(((bounded_val + 100) / 200) * (max_ - min_) + min_)
            elif self.motors[name].norm_mode is MotorNormMode.RANGE_0_100:
                bounded_val = min(100.0, max(0.0, val))
                unnormalized_values[id_] = int((bounded_val / 100) * (max_ - min_) + min_)
            else:
                # TODO(alibers): velocity and degree modes
                raise NotImplementedError

        return unnormalized_values

    @abc.abstractmethod
    def _encode_value(
        self, value: int, data_name: str | None = None, n_bytes: int | None = None
    ) -> dict[int, int]:
        pass

    @abc.abstractmethod
    def _decode_value(
        self, value: int, data_name: str | None = None, n_bytes: int | None = None
    ) -> dict[int, int]:
        pass

    @staticmethod
    @abc.abstractmethod
    def _split_int_to_bytes(value: int, n_bytes: int) -> list[int]:
        """
        Splits an unsigned integer into a list of bytes in little-endian order.

        This function extracts the individual bytes of an integer based on the
        specified number of bytes (`n_bytes`). The output is a list of integers,
        each representing a byte (0-255).

        **Byte order:** The function returns bytes in **little-endian format**,
        meaning the least significant byte (LSB) comes first.

        Args:
            value (int): The unsigned integer to be converted into a byte list. Must be within
                the valid range for the specified `n_bytes`.
            n_bytes (int): The number of bytes to use for conversion. Supported values:
                - 1 (for values 0 to 255)
                - 2 (for values 0 to 65,535)
                - 4 (for values 0 to 4,294,967,295)

        Raises:
            ValueError: If `value` is negative or exceeds the maximum allowed for `n_bytes`.
            NotImplementedError: If `n_bytes` is not 1, 2, or 4.

        Returns:
            list[int]: A list of integers, each representing a byte in **little-endian order**.

        Examples:
            >>> split_int_bytes(0x12, 1)
            [18]
            >>> split_int_bytes(0x1234, 2)
            [52, 18]  # 0x1234 → 0x34 0x12 (little-endian)
            >>> split_int_bytes(0x12345678, 4)
            [120, 86, 52, 18]  # 0x12345678 → 0x78 0x56 0x34 0x12
        """
        pass

    def ping(self, motor: NameOrID, num_retry: int = 0, raise_on_error: bool = False) -> int | None:
        id_ = self._get_motor_id(motor)
        for n_try in range(1 + num_retry):
            model_number, comm, error = self.packet_handler.ping(self.port_handler, id_)
            if self._is_comm_success(comm):
                break
            logger.debug(f"ping failed for {id_=}: {n_try=} got {comm=} {error=}")

        if not self._is_comm_success(comm):
            if raise_on_error:
                raise ConnectionError(self.packet_handler.getRxPacketError(comm))
            else:
                return
        if self._is_error(error):
            if raise_on_error:
                raise RuntimeError(self.packet_handler.getTxRxResult(comm))
            else:
                return

        return model_number

    @abc.abstractmethod
    def broadcast_ping(
        self, num_retry: int = 0, raise_on_error: bool = False
    ) -> dict[int, list[int, str]] | None:
        pass

    @overload
    def sync_read(
        self, data_name: str, motors: None = ..., *, normalize: bool = ..., num_retry: int = ...
    ) -> dict[str, Value]: ...
    @overload
    def sync_read(
        self,
        data_name: str,
        motors: NameOrID | list[NameOrID],
        *,
        normalize: bool = ...,
        num_retry: int = ...,
    ) -> dict[NameOrID, Value]: ...
    def sync_read(
        self,
        data_name: str,
        motors: NameOrID | list[NameOrID] | None = None,
        *,
        normalize: bool = True,
        num_retry: int = 0,
    ) -> dict[NameOrID, Value]:
        if not self.is_connected:
            raise DeviceNotConnectedError(
                f"{self.__class__.__name__}('{self.port}') is not connected. You need to run `{self.__class__.__name__}.connect()`."
            )

        id_key_map: dict[int, NameOrID] = {}
        if motors is None:
            id_key_map = {m.id: name for name, m in self.motors.items()}
        elif isinstance(motors, (str, int)):
            id_key_map = {self._get_motor_id(motors): motors}
        elif isinstance(motors, list):
            id_key_map = {self._get_motor_id(m): m for m in motors}
        else:
            raise TypeError(motors)

        motor_ids = list(id_key_map)

        comm, ids_values = self._sync_read(data_name, motor_ids, num_retry=num_retry)
        if not self._is_comm_success(comm):
            raise ConnectionError(
                f"Failed to sync read '{data_name}' on {motor_ids=} after {num_retry + 1} tries."
                f"{self.packet_handler.getTxRxResult(comm)}"
            )

        if normalize and data_name in self.normalization_required:
            ids_values = self._normalize(data_name, ids_values)

        return {id_key_map[id_]: val for id_, val in ids_values.items()}

    def _sync_read(
        self, data_name: str, motor_ids: list[str], model: str | None = None, num_retry: int = 0
    ) -> tuple[int, dict[int, int]]:
        if self._has_different_ctrl_tables:
            models = [self._id_to_model(id_) for id_ in motor_ids]
            assert_same_address(self.model_ctrl_table, models, data_name)

        model = self._id_to_model(next(iter(motor_ids))) if model is None else model
        addr, n_bytes = get_address(self.model_ctrl_table, model, data_name)
        self._setup_sync_reader(motor_ids, addr, n_bytes)

        # FIXME(aliberts, pkooij): We should probably not have to do this.
        # Let's try to see if we can do with better comm status handling instead.
        # self.port_handler.ser.reset_output_buffer()
        # self.port_handler.ser.reset_input_buffer()

        for n_try in range(1 + num_retry):
            comm = self.sync_reader.txRxPacket()
            if self._is_comm_success(comm):
                break
            logger.debug(f"Failed to sync read '{data_name}' ({addr=} {n_bytes=}) on {motor_ids=} ({n_try=})")
            logger.debug(self.packet_handler.getRxPacketError(comm))

        values = {}
        for id_ in motor_ids:
            val = self.sync_reader.getData(id_, addr, n_bytes)
            values[id_] = self._decode_value(val, data_name, n_bytes)

        return comm, values

    def _setup_sync_reader(self, motor_ids: list[str], addr: int, n_bytes: int) -> None:
        self.sync_reader.clearParam()
        self.sync_reader.start_address = addr
        self.sync_reader.data_length = n_bytes
        for id_ in motor_ids:
            self.sync_reader.addParam(id_)

    # TODO(aliberts, pkooij): Implementing something like this could get even much faster read times if need be.
    # Would have to handle the logic of checking if a packet has been sent previously though but doable.
    # This could be at the cost of increase latency between the moment the data is produced by the motors and
    # the moment it is used by a policy.
    # def _async_read(self, motor_ids: list[str], address: int, n_bytes: int):
    #     if self.sync_reader.start_address != address or self.sync_reader.data_length != n_bytes or ...:
    #         self._setup_sync_reader(motor_ids, address, n_bytes)
    #     else:
    #         self.sync_reader.rxPacket()
    #         self.sync_reader.txPacket()

    #     for id_ in motor_ids:
    #         value = self.sync_reader.getData(id_, address, n_bytes)

    def sync_write(
        self,
        data_name: str,
        values: Value | dict[NameOrID, Value],
        *,
        normalize: bool = True,
        num_retry: int = 0,
    ) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(
                f"{self.__class__.__name__}('{self.port}') is not connected. You need to run `{self.__class__.__name__}.connect()`."
            )

        if isinstance(values, int):
            ids_values = {id_: values for id_ in self.ids}
        elif isinstance(values, dict):
            ids_values = {self._get_motor_id(motor): val for motor, val in values.items()}
        else:
            raise TypeError(f"'values' is expected to be a single value or a dict. Got {values}")

        if normalize and data_name in self.normalization_required and self.calibration is not None:
            ids_values = self._unnormalize(data_name, ids_values)

        comm = self._sync_write(data_name, ids_values, num_retry=num_retry)
        if not self._is_comm_success(comm):
            raise ConnectionError(
                f"Failed to sync write '{data_name}' with {ids_values=} after {num_retry + 1} tries."
                f"\n{self.packet_handler.getTxRxResult(comm)}"
            )

    def _sync_write(self, data_name: str, ids_values: dict[int, int], num_retry: int = 0) -> int:
        if self._has_different_ctrl_tables:
            models = [self._id_to_model(id_) for id_ in ids_values]
            assert_same_address(self.model_ctrl_table, models, data_name)

        model = self._id_to_model(next(iter(ids_values)))
        addr, n_bytes = get_address(self.model_ctrl_table, model, data_name)
        ids_values = {id_: self._encode_value(value, data_name, n_bytes) for id_, value in ids_values.items()}
        self._setup_sync_writer(ids_values, addr, n_bytes)

        for n_try in range(1 + num_retry):
            comm = self.sync_writer.txPacket()
            if self._is_comm_success(comm):
                break
            logger.debug(
                f"Failed to sync write '{data_name}' ({addr=} {n_bytes=}) with {ids_values=} ({n_try=})"
            )
            logger.debug(self.packet_handler.getRxPacketError(comm))

        return comm

    def _setup_sync_writer(self, ids_values: dict[int, int], addr: int, n_bytes: int) -> None:
        self.sync_writer.clearParam()
        self.sync_writer.start_address = addr
        self.sync_writer.data_length = n_bytes
        for id_, value in ids_values.items():
            data = self._split_int_to_bytes(value, n_bytes)
            self.sync_writer.addParam(id_, data)

    def write(
        self, data_name: str, motor: NameOrID, value: Value, *, normalize: bool = True, num_retry: int = 0
    ) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(
                f"{self.__class__.__name__}('{self.port}') is not connected. You need to run `{self.__class__.__name__}.connect()`."
            )

        id_ = self._get_motor_id(motor)

        if normalize and data_name in self.normalization_required and self.calibration is not None:
            id_value = self._unnormalize(data_name, {id_: value})
            value = id_value[id_]

        comm, error = self._write(data_name, id_, value, num_retry=num_retry)
        if not self._is_comm_success(comm):
            raise ConnectionError(
                f"Failed to write '{data_name}' on {id_=} with '{value}' after {num_retry + 1} tries."
                f"\n{self.packet_handler.getTxRxResult(comm)}"
            )
        elif self._is_error(error):
            raise RuntimeError(
                f"Failed to write '{data_name}' on {id_=} with '{value}' after {num_retry + 1} tries."
                f"\n{self.packet_handler.getRxPacketError(error)}"
            )

    def _write(self, data_name: str, motor_id: int, value: int, num_retry: int = 0) -> tuple[int, int]:
        model = self._id_to_model(motor_id)
        addr, n_bytes = get_address(self.model_ctrl_table, model, data_name)
        value = self._encode_value(value, data_name, n_bytes)
        data = self._split_int_to_bytes(value, n_bytes)

        for n_try in range(1 + num_retry):
            comm, error = self.packet_handler.writeTxRx(self.port_handler, motor_id, addr, n_bytes, data)
            if self._is_comm_success(comm):
                break
            logger.debug(
                f"Failed to write '{data_name}' ({addr=} {n_bytes=}) on {motor_id=} with '{value}' ({n_try=})"
            )
            logger.debug(self.packet_handler.getRxPacketError(comm))

        return comm, error

    def disconnect(self) -> None:
        if not self.is_connected:
            raise DeviceNotConnectedError(
                f"{self.__class__.__name__}('{self.port}') is not connected. Try running `{self.__class__.__name__}.connect()` first."
            )

        self.port_handler.closePort()
        logger.debug(f"{self.__class__.__name__} disconnected.")
