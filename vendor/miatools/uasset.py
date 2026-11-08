"""Reading the package summary of cooked, unversioned UE4.25 ``.uasset`` files: names, imports, exports and the
names referenced by Blueprint functions.

Use it to find the exact class, property and function names before calling them from UE4SS (unknown names
crash UE4SS 3.0.1).
"""
import struct
from dataclasses import dataclass

from .pak import read_fstring, read_game_file

_IMPORT_SIZE = 28
_EXPORT_SIZE = 104


@dataclass(frozen=True)
class Import:
    """One entry of the import table."""

    class_package: str
    class_name: str
    outer: int
    name: str


@dataclass(frozen=True)
class Export:
    """One entry of the export table."""

    class_index: int
    name: str
    serial_size: int
    serial_offset: int


class Package:
    """Parsed summary of a ``.uasset`` file, with its optional ``.uexp`` data."""

    def __init__(self, uasset, uexp=b""):
        """Parse the summary.

        Args:
            uasset: bytes of the ``.uasset`` file.
            uexp: bytes of the matching ``.uexp`` file, needed only by ``function_names``.
        """
        self.data = uasset
        self.uexp = uexp
        self._parse_summary()
        self.names = self._read_names()
        self.imports = self._read_imports()
        self.exports = self._read_exports()

    @classmethod
    def from_game(cls, internal_path):
        """Load a package from the official game paks by its internal ``.uasset`` path."""
        uexp_path = internal_path.removesuffix(".uasset") + ".uexp"
        try:
            uexp = read_game_file(uexp_path)
        except FileNotFoundError:
            uexp = b""
        return cls(read_game_file(internal_path), uexp)

    @classmethod
    def from_file(cls, path):
        """Load a package from an extracted ``.uasset`` file (and its ``.uexp`` next to it, if present)."""
        path = str(path)
        uexp_path = path.removesuffix(".uasset") + ".uexp"
        try:
            uexp = open(uexp_path, "rb").read()
        except FileNotFoundError:
            uexp = b""
        return cls(open(path, "rb").read(), uexp)

    def _parse_summary(self):
        """Read the offsets and counts of the package summary."""
        b = self.data
        pos = 4 + 4 + 4 + 4 + 4  # tag, legacy version, legacy UE3 version, UE4 version, licensee version
        custom_versions = struct.unpack_from("<i", b, pos)[0]
        pos += 4 + custom_versions * 20
        self.header_size = struct.unpack_from("<i", b, pos)[0]
        pos += 4
        _, pos = read_fstring(b, pos)  # folder name
        pos += 4  # package flags
        self._name_count, self._name_offset = struct.unpack_from("<ii", b, pos)
        pos += 8 + 8  # names, gatherable text data
        self._export_count, self._export_offset, self._import_count, self._import_offset = \
            struct.unpack_from("<iiii", b, pos)

    def _read_names(self):
        """Return the name table."""
        names, pos = [], self._name_offset
        for _ in range(self._name_count):
            name, pos = read_fstring(self.data, pos)
            pos += 4  # hash
            names.append(name)
        return names

    def _fname(self, pos):
        """Return the ``FName`` stored at ``pos`` (index + number)."""
        index, number = struct.unpack_from("<ii", self.data, pos)
        return self.names[index] + (f"_{number - 1}" if number else "")

    def _read_imports(self):
        """Return the import table."""
        result = []
        for i in range(self._import_count):
            pos = self._import_offset + i * _IMPORT_SIZE
            outer = struct.unpack_from("<i", self.data, pos + 16)[0]
            result.append(Import(self._fname(pos), self._fname(pos + 8), outer, self._fname(pos + 20)))
        return result

    def _read_exports(self):
        """Return the export table."""
        result = []
        for i in range(self._export_count):
            pos = self._export_offset + i * _EXPORT_SIZE
            class_index = struct.unpack_from("<i", self.data, pos)[0]
            size, offset = struct.unpack_from("<qq", self.data, pos + 28)
            result.append(Export(class_index, self._fname(pos + 16), size, offset))
        return result

    def import_path(self, i):
        """Return the full dotted path of import ``i`` (e.g. ``/Script/UMG.Image``)."""
        imp = self.imports[i]
        prefix = self.import_path(-imp.outer - 1) + "." if imp.outer < 0 else ""
        return prefix + imp.name

    def export_class(self, export):
        """Return the class name of ``export`` when the class is imported, else ``"?"``."""
        if export.class_index < 0:
            return self.imports[-export.class_index - 1].name
        return "?"

    def function_names(self, wanted=()):
        """Return ``{function: [names referenced in its bytecode]}`` for the Blueprint functions.

        The names are every ``FName`` reference found in the serialized function, parameters included.

        Args:
            wanted: optional function names to keep; all functions when empty.
        """
        if not self.uexp:
            raise ValueError("The .uexp data is needed to read function bodies")
        result = {}
        for export in self.exports:
            if self.export_class(export) != "Function" or (wanted and export.name not in wanted):
                continue
            start = export.serial_offset - self.header_size
            body = self.uexp[start:start + export.serial_size]
            refs = []
            for k in range(len(body) - 8):
                index, number = struct.unpack_from("<ii", body, k)
                if 0 <= index < len(self.names) and number == 0 and self.names[index] != "None":
                    refs.append(self.names[index])
            result[export.name] = refs
        return result
