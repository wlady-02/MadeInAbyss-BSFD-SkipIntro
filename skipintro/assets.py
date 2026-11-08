"""Patching float values in cooked Blueprint assets."""
import re
import struct

from miatools.uasset import Package

FLOAT_CONST = 0x1E  # EX_FloatConst opcode in Kismet bytecode
FINAL_FUNCTION = 0x1C  # EX_FinalFunction opcode, followed by the function's package index
CALL_MATH = 0x68  # EX_CallMath opcode (static library calls such as Delay)
SELF = 0x17  # EX_Self opcode

# End of the PlayAnimation arguments as the title Blueprint passes them: PlayMode Forward (EX_ByteConst 0),
# PlaybackSpeed EX_FloatConst 1.0, bRestoreState EX_False.
_PLAY_TAIL = bytes.fromhex("2400") + bytes([FLOAT_CONST]) + struct.pack("<f", 1.0) + bytes.fromhex("28")
_PLAY_SPEED_IN_TAIL = 3
_PLAY_ARGS_MAX = 80
# A one-element FFieldPath (count 1, FName index, FName number 0): how bytecode names a property.
_FIELD_PATH = re.compile(rb"\x01\x00\x00\x00(....)\x00\x00\x00\x00", re.S)

# Extra bytes after the property tag header, by property type.
_TAG_EXTRA = {"StructProperty": 24, "BoolProperty": 1, "ByteProperty": 8, "EnumProperty": 8,
              "ArrayProperty": 8, "SetProperty": 8, "MapProperty": 16}


class UnexpectedValue(ValueError):
    """Raised when the game data differs from what the patch expects (e.g. after a game update)."""


def float_property_offset(package, prop):
    """Return the offset in the ``.uexp`` of the value of FloatProperty ``prop`` of the class default object.

    Args:
        package: a ``Package`` loaded with its ``.uexp``.
        prop: property name, e.g. ``"ShowTime"``.
    """
    names, uexp = package.names, package.uexp
    cdo = next(e for e in package.exports if e.name.startswith("Default__"))
    pos = cdo.serial_offset - package.header_size
    end = pos + cdo.serial_size
    while pos < end:
        name = names[struct.unpack_from("<i", uexp, pos)[0]]
        if name == "None":
            break
        kind = names[struct.unpack_from("<i", uexp, pos + 8)[0]]
        size = struct.unpack_from("<i", uexp, pos + 16)[0]
        pos += 24 + _TAG_EXTRA.get(kind, 0)
        pos += 1 + (16 if uexp[pos] else 0)  # property GUID flag and optional GUID
        if name == prop and kind == "FloatProperty":
            return pos
        pos += size
    raise UnexpectedValue(f"FloatProperty {prop} not found")


def set_float(data, offset, expected, value):
    """Overwrite the float at ``offset`` in ``data`` after checking it still equals ``expected``."""
    current = struct.unpack_from("<f", data, offset)[0]
    if abs(current - expected) > 1e-6:
        raise UnexpectedValue(f"found {current}, expected {expected}: has the game changed?")
    struct.pack_into("<f", data, offset, value)


def replace_float_constants(data, old, new):
    """Replace every ``EX_FloatConst old`` in bytecode ``data`` with ``new``; return the number replaced."""
    needle = bytes([FLOAT_CONST]) + struct.pack("<f", old)
    count = data.count(needle)
    data[:] = data.replace(needle, bytes([FLOAT_CONST]) + struct.pack("<f", new))
    return count


def _import_index(package, name):
    """Return the package index (negative) of the import called ``name``."""
    for i, item in enumerate(package.imports):
        if item.name == name:
            return -i - 1
    raise UnexpectedValue(f"import {name} not found")


def _animation_of(package, args):
    """Return the name of the animation passed as first argument in the bytecode ``args``, or ``None``."""
    names = [struct.unpack("<i", m.group(1))[0] for m in _FIELD_PATH.finditer(args)]
    names = [package.names[i] for i in names if 0 <= i < len(package.names)]
    return names[-1] if names else None


def speed_up_animations(package, uexp, animations, speed):
    """Set the PlaybackSpeed of every ``PlayAnimation`` call on one of ``animations`` to ``speed``.

    Args:
        package: the ``Package`` the bytecode belongs to.
        uexp: ``bytearray`` with the ``.uexp`` data, patched in place.
        animations: widget animation names, e.g. ``{"In", "DeskIn"}``.
        speed: the new playback speed.

    Returns:
        The number of calls changed.
    """
    call = bytes([FINAL_FUNCTION]) + struct.pack("<i", _import_index(package, "PlayAnimation"))
    count = 0
    for match in re.finditer(re.escape(call), uexp):
        args = bytes(uexp[match.end():match.end() + _PLAY_ARGS_MAX])
        tail = args.find(_PLAY_TAIL)
        if tail >= 0 and _animation_of(package, args[:tail]) in animations:
            set_float(uexp, match.end() + tail + _PLAY_SPEED_IN_TAIL, 1.0, speed)
            count += 1
    return count


def shorten_delays(package, uexp, value):
    """Set every ``Delay(self, <constant>)`` duration longer than ``value`` in the bytecode to ``value``.

    Args:
        package: the ``Package`` the bytecode belongs to.
        uexp: ``bytearray`` with the ``.uexp`` data, patched in place.
        value: the new duration in seconds.

    Returns:
        The list of the original durations.
    """
    call = bytes([CALL_MATH]) + struct.pack("<i", _import_index(package, "Delay")) + bytes([SELF, FLOAT_CONST])
    found = []
    for match in re.finditer(re.escape(call), uexp):
        old = struct.unpack_from("<f", uexp, match.end())[0]
        if old <= value:
            continue
        struct.pack_into("<f", uexp, match.end(), value)
        found.append(round(old, 3))
    return found


def patch_package(package, properties, constants, value, animations=(), speed=1.0, delays=False):
    """Return the patched ``.uexp`` bytes of ``package``.

    Args:
        package: the ``Package`` to patch, with its ``.uexp``.
        properties: ``{property name: expected current value}`` of class-default floats to overwrite.
        constants: float constants of the bytecode to overwrite everywhere.
        value: the new value of all of them.
        animations: widget animations whose ``PlayAnimation`` calls get playback ``speed``.
        speed: playback speed for ``animations``.
        delays: also set every constant ``Delay`` duration to ``value``.

    Returns:
        ``(patched uexp bytes, list of human-readable changes)``.
    """
    uexp = bytearray(package.uexp)
    changes = []
    for prop, expected in properties.items():
        set_float(uexp, float_property_offset(package, prop), expected, value)
        changes.append(f"{prop}: {expected} -> {value}")
    for old in constants:
        count = replace_float_constants(uexp, old, value)
        changes.append(f"{count} constants {old} -> {value}")
    if animations:
        count = speed_up_animations(package, uexp, set(animations), speed)
        changes.append(f"{count} animations {sorted(animations)} at speed {speed}")
    if delays:
        changes.append(f"delays {shorten_delays(package, uexp, value)} -> {value}")
    return bytes(uexp), changes
