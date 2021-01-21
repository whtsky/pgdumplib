"""
The :py:class:`~pgdumplib.dump.Dump` class exposes methods to
:py:meth:`load <pgdumplib.dump.Dump.load>` an existing dump,
to :py:meth:`add an entry <pgdumplib.dump.Dump.add_entry>` to a dump,
to :py:meth:`add table data <pgdumplib.dump.Dump.add_data>` to a dump,
to :py:meth:`add blob data <pgdumplib.dump.Dump.add_blob>` to a dump,
and to :py:meth:`save <pgdumplib.dump.Dump.save>` a new dump.

There are :doc:`converters` that are available to format the data that is
returned by :py:meth:`~pgdumplib.dump.Dump.read_data`. The converter
is passed in during construction of a new :py:class:`~pgdumplib.dump.Dump`,
and is also available as an argument to :py:func:`pgdumplib.load`.

The default converter, :py:class:`~pgdumplib.converters.DataConverter` will
return all fields as strings, only replacing ``NULL`` with
:py:const:`None`. The :py:class:`~pgdumplib.converters.SmartDataConverter`
will attempt to convert all columns to native Python data types.

When loading or creating a dump, the table and blob data are stored in
gzip compressed data files in a temporary directory that is automatically
cleaned up when the :py:class:`~pgdumplib.dump.Dump` instance is released.

"""
import contextlib
import dataclasses
import datetime
import gzip
import io
import logging
import os
import pathlib
import re
import struct
import tempfile
import typing
import zlib

import toposort

from pgdumplib import constants, converters, exceptions, version

LOGGER = logging.getLogger(__name__)

ENCODING_PATTERN = re.compile(r"^.*=\s+'(.*)'")

VERSION_INFO = '{} (pgdumplib {})'


class Dump:
    """Create a new instance of the :py:class:`~pgdumplib.dump.Dump` class

    Once created, the instance of :py:class:`~pgdumplib.dump.Dump` can
    be used to read existing dumps or to create new ones.

    :param str dbname: The database name for the dump (Default: ``pgdumplib``)
    :param str encoding: The data encoding (Default: ``UTF8``)
    :param converter: The data converter class to use
        (Default: :py:class:`pgdumplib.converters.DataConverter`)

    """

    def __init__(
        self, dbname: str = 'pgdumplib', encoding: str = 'UTF8',
        converter: typing.Optional[typing.Union[
            typing.Type[converters.DataConverter],
            typing.Type[converters.NoOpConverter],
            typing.Type[converters.SmartDataConverter]]] = None,
        appear_as: str = '12.0'):
        self.compression = False
        self.dbname = dbname
        self.dump_version = VERSION_INFO.format(appear_as, version)
        self.encoding = encoding
        self.entries = [
            Entry(
                dump_id=1, tag=constants.ENCODING, desc=constants.ENCODING,
                defn="SET client_encoding = '{}';\n".format(self.encoding)),
            Entry(
                dump_id=2, tag='STDSTRINGS', desc='STDSTRINGS',
                defn="SET standard_conforming_strings = 'on';\n"),
            Entry(
                dump_id=3, tag='SEARCHPATH', desc='SEARCHPATH',
                defn='SELECT pg_catalog.set_config('
                     "'search_path', '', false);\n")
        ]
        self.server_version = self.dump_version
        self.timestamp = datetime.datetime.now()

        converter = converter or converters.DataConverter
        self._converter: converters.DataConverter = converter()
        self._format: str = 'Custom'
        self._intsize: int = 4
        self._offsize: int = 8
        self._temp_dir = tempfile.TemporaryDirectory()
        k_version = self._get_k_version(
            tuple(int(v) for v in appear_as.split('.')))
        self._vmaj: int = k_version[0]
        self._vmin: int = k_version[1]
        self._vrev: int = k_version[2]
        self._writers: typing.Dict[int, TableData] = {}

    def __repr__(self) -> str:
        return '<Dump format={!r} timestamp={!r} entry_count={!r}>'.format(
            self._format, self.timestamp.isoformat(), len(self.entries))

    def add_entry(
        self,
        desc: str,
        namespace: typing.Optional[str] = None,
        tag: typing.Optional[str] = None,
        owner: typing.Optional[str] = None,
        defn: typing.Optional[str] = None,
        drop_stmt: typing.Optional[str] = None,
        copy_stmt: typing.Optional[str] = None,
        dependencies: typing.Optional[typing.List[int]] = None,
        tablespace: typing.Optional[str] = None,
        tableam: typing.Optional[str] = None,
        dump_id: typing.Optional[int] = None) -> 'Entry':
        """Add an entry to the dump

        The ``namespace`` and ``tag`` are required.

        A :py:exc:`ValueError` will be raised if `desc` is not value that
        is known in :py:module:`pgdumplib.constants`.

        The section is

        When adding data, use :py:meth:`~Dump.table_data_writer` instead of
        invoking :py:meth:`~Dump.add_entry` directly.

        If ``dependencies`` are specified, they will be validated and if a
        ``dump_id`` is specified and no entry is found with that ``dump_id``,
        a :py:exc:`ValueError` will be raised.

        Other omitted values will be set to the default values will be set to
        the defaults specified in the :py:class:`pgdumplib.dump.Entry`
        class.

        The ``dump_id`` will be auto-calculated based upon the existing entries
        if it is not specified.

        .. note:: The creation of ad-hoc blobs is not supported.

        :param str desc: The entry description
        :param str namespace: The namespace of the entry
        :param str tag: The name/table/relation/etc of the entry
        :param str owner: The owner of the object in Postgres
        :param str defn: The DDL definition for the entry
        :param drop_stmt: A drop statement used to drop the entry before
        :param copy_stmt: A copy statement used when there is a corresponding
            data section.
        :param list dependencies: A list of dump_ids of objects that the entry
            is dependent upon.
        :param str tablespace: The tablespace to use
        :param str tableam: The table access method
        :param int dump_id: The dump id, will be auto-calculated if left empty
        :raises: :py:exc:`ValueError`
        :rtype: pgdumplib.dump.Entry

        """
        if desc not in constants.SECTION_MAPPING:
            raise ValueError('Invalid desc: {}'.format(desc))

        if dump_id is not None and dump_id < 1:
            raise ValueError('dump_id must be greater than 1')

        dump_ids = [e.dump_id for e in self.entries]

        if dump_id and dump_id in dump_ids:
            raise ValueError('dump_id {!r} is already assigned', dump_id)

        for dependency in dependencies or []:
            if dependency not in dump_ids:
                raise ValueError(
                    'Dependency dump_id {!r} not found'.format(dependency))
        self.entries.append(Entry(
            dump_id or self._next_dump_id(), False, '', '', tag or '', desc,
            defn or '', drop_stmt or '', copy_stmt or '', namespace or '',
            tablespace or '', tableam or '', owner or '', False,
            dependencies or []))
        return self.entries[-1]

    def blobs(self) -> typing.Generator[typing.Tuple[int, bytes], None, None]:
        """Iterator that returns each blob in the dump

        :rtype: tuple(int, bytes)

        """

        def read_oid(fd: typing.BinaryIO) -> typing.Optional[int]:
            """Small helper function to deduplicate code"""
            try:
                return struct.unpack('I', fd.read(4))[0]
            except struct.error:
                return None

        for entry in self._data_entries:
            if entry.desc == constants.BLOBS:
                with self._tempfile(entry.dump_id, 'rb') as handle:
                    oid: typing.Optional[int] = read_oid(handle)
                    while oid:
                        length: int = struct.unpack('I', handle.read(4))[0]
                        yield oid, handle.read(length)
                        oid = read_oid(handle)

    def get_entry(self, dump_id: int) -> typing.Optional['Entry']:
        """Return the entry for the given `dump_id`

        :param int dump_id: The dump ID of the entry to return.
        :rtype: pgdumplib.dump.Entry or None

        """
        for entry in self.entries:
            if entry.dump_id == dump_id:
                return entry
        return None

    def load(self, fp: typing.BinaryIO) -> 'Dump':
        """Load the Dumpfile, including extracting all data into a temporary
        directory

        :param os.PathLike path: The path of the dump to load
        :raises: :py:exc:`RuntimeError`
        :raises: :py:exc:`ValueError`

        """
        self.entries = []  # Wipe out pre-existing entries
        self._read_header(fp)
        if not constants.MIN_VER <= self.version <= constants.MAX_VER:
            raise ValueError(
                'Unsupported backup version: {}.{}.{}'.format(
                    *self.version))

        self.compression = self._read_int(fp) != 0
        self.timestamp = self._read_timestamp(fp)
        self.dbname = self._read_bytes(fp).decode(self.encoding)
        self.server_version = self._read_bytes(fp).decode(self.encoding)
        self.dump_version = self._read_bytes(fp).decode(self.encoding)

        self._read_entries(fp)
        self._set_encoding()

        # Cache table data and blobs
        for entry in self._data_entries:
            if entry.data_state == constants.K_OFFSET_NO_DATA:
                continue
            elif entry.data_state != constants.K_OFFSET_POS_SET:
                raise RuntimeError('Unsupported data format')
            fp.seek(entry.offset, io.SEEK_SET)
            block_type, dump_id = self._read_block_header(fp)
            if not dump_id or dump_id != entry.dump_id:
                raise RuntimeError('Dump IDs do not match ({} != {}'.format(
                    dump_id, entry.dump_id))
            if block_type == constants.BLK_DATA:
                self._cache_table_data(dump_id)
            elif block_type == constants.BLK_BLOBS:
                self._cache_blobs(fp, dump_id)
            else:
                raise RuntimeError('Unknown block type: {}'.format(block_type))
        return self

    def lookup_entry(self, desc: str, namespace: str, tag: str) \
        -> typing.Optional['Entry']:
        """Return the entry for the given namespace and tag

        :param str desc: The desc / object type of the entry
        :param str namespace: The namespace of the entry
        :param str tag: The tag/relation/table name
        :param str section: The dump section the entry is for
        :raises: :py:exc:`ValueError`
        :rtype: pgdumplib.dump.Entry or None

        """
        if desc not in constants.SECTION_MAPPING:
            raise ValueError('Invalid desc: {}'.format(desc))
        for entry in [e for e in self.entries if e.desc == desc]:
            if entry.namespace == namespace and entry.tag == tag:
                return entry
        return None

    def save(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Save the Dump file to the specified path

        :param os.PathLike path: The path to save the dump to

        """
        self.compression = False
        self._save(fp)

    def table_data(self, namespace: str, table: str) \
        -> typing.Generator[
            typing.Union[str, typing.Tuple[typing.Any, ...]], None, None]:
        """Iterator that returns data for the given namespace and table

        :param str namespace: The namespace/schema for the table
        :param str table: The table name
        :raises: :py:exc:`pgdumplib.exceptions.EntityNotFoundError`

        """
        for entry in self._data_entries:
            if entry.namespace == namespace and entry.tag == table:
                for row in self._read_table_data(entry.dump_id):
                    yield self._converter.convert(row)
                return
        raise exceptions.EntityNotFoundError(namespace=namespace, table=table)

    @contextlib.contextmanager
    def table_data_writer(self, entry: 'Entry', columns: typing.Sequence) \
        -> typing.Generator['TableData', None, None]:
        """A context manager that is used to return a
        :py:class:`~pgdumplib.dump.TableData` instance, which can be used
        to add table data to the dump.

        When invoked for a given entry containing the table definition,

        :param Entry entry: The entry for the table to add data for
        :param columns: The ordered list of table columns
        :type columns: list or tuple
        :rtype: TableData

        """
        if entry.dump_id not in self._writers.keys():
            dump_id = self._next_dump_id()
            self.entries.append(Entry(
                dump_id=dump_id, had_dumper=True, tag=entry.tag,
                desc=constants.TABLE_DATA,
                copy_stmt='COPY {}.{} ({}) FROM stdin;'.format(
                    entry.namespace, entry.tag, ', '.join(columns)),
                namespace=entry.namespace, owner=entry.owner,
                dependencies=[entry.dump_id],
                data_state=constants.K_OFFSET_POS_NOT_SET))
            self._writers[entry.dump_id] = TableData(
                dump_id, self._temp_dir.name, self.encoding)
        yield self._writers[entry.dump_id]
        return None

    @property
    def version(self) -> typing.Tuple[int, int, int]:
        """Return the version as a tuple to make version comparisons easier.

        :rtype: tuple

        """
        return self._vmaj, self._vmin, self._vrev

    def _cache_blobs(self, fp: typing.BinaryIO, dump_id: int) -> typing.NoReturn:
        """Create a temp cache file for blob data

        :param int dump_id: The dump ID for the filename

        """
        count = 0
        with self._tempfile(dump_id, 'wb') as handle:
            for oid, blob in self._read_blobs(fp):
                handle.write(struct.pack('I', oid))
                handle.write(struct.pack('I', len(blob)))
                handle.write(blob)
                count += 1

    def _cache_table_data(self, dump_id: int) -> typing.NoReturn:
        """Create a temp cache file for the table data

        :param int dump_id: The dump ID for the filename

        """
        with self._tempfile(dump_id, 'wb') as handle:
            handle.write(self._read_data())

    @property
    def _data_entries(self) -> typing.List['Entry']:
        """Return the list of entries that are in the data section

        :rtype: list

        """
        return [e for e in self.entries if e.section == constants.SECTION_DATA]

    @staticmethod
    def _get_k_version(appear_as: typing.Tuple[int, int]) \
        -> typing.Tuple[int, int, int]:
        for (min_ver, max_ver), value in constants.K_VERSION_MAP.items():
            if min_ver <= appear_as <= max_ver:
                return value
        raise RuntimeError(
            'Unsupported PostgreSQL version: {}'.format(appear_as))

    def _next_dump_id(self) -> int:
        """Get the next ``dump_id`` that is available for adding an entry

        :rtype: int

        """
        return max(e.dump_id for e in self.entries) + 1

    def _read_blobs(self, fp: typing.BinaryIO) -> typing.Generator[
        typing.Tuple[int, bytes], None, None]:
        """Read blobs, returning a tuple of the blob ID and the blob data

        :rtype: (int, bytes)
        :raises: :exc:`RuntimeError`

        """
        oid = self._read_int(fp)
        while oid is not None and oid > 0:
            data = self._read_data()
            yield oid, data
            oid = self._read_int(fp)
            if oid == 0:
                oid = self._read_int(fp)

    def _read_block_header(self, fp: typing.BinaryIO) -> typing.Tuple[bytes, typing.Optional[int]]:
        """Read the block header in

        :rtype: bytes, int

        """
        return fp.read(1), self._read_int(fp)

    def _read_byte(self, fp: typing.BinaryIO) -> typing.Optional[int]:
        """Read in an individual byte

        :rtype: int

        """
        try:
            return struct.unpack('B', fp.read(1))[0]
        except struct.error:
            return None

    def _read_bytes(self, fp: typing.BinaryIO) -> bytes:
        """Read in a byte stream

        :rtype: bytes

        """
        length = self._read_int(fp)
        if length and length > 0:
            value = fp.read(length)
            return value
        return b''

    def _read_data(self) -> bytes:
        """Read a data block, returning the bytes.

        :rtype: bytes

        """
        if self.compression:
            return self._read_data_compressed()
        return self._read_data_uncompressed()

    def _read_data_compressed(self, fp: typing.BinaryIO) -> bytes:
        """Read a compressed data block

        :rtype: bytes

        """
        buffer = io.BytesIO()
        chunk = b''
        decompress = zlib.decompressobj()
        while True:
            chunk_size = self._read_int(fp)
            if not chunk_size:  # pragma: nocover
                break
            chunk += fp.read(chunk_size)
            buffer.write(decompress.decompress(chunk))
            chunk = decompress.unconsumed_tail
            if chunk_size < constants.ZLIB_IN_SIZE:
                break
        return buffer.getvalue()

    def _read_data_uncompressed(self, fp: typing.BinaryIO) -> bytes:
        """Read an uncompressed data block

        :rtype: bytes

        """
        buffer = io.BytesIO()
        while True:
            block_length = self._read_int(fp)
            if not block_length or block_length <= 0:
                break
            buffer.write(fp.read(block_length))
        return buffer.getvalue()

    def _read_dependencies(self, fp: typing.BinaryIO) -> list:
        """Read in the dependencies for an entry.

        :rtype: list

        """
        values = set({})
        while True:
            value = self._read_bytes(fp)
            if not value:
                break
            values.add(int(value))
        return sorted(values)

    def _read_entries(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Read in all of the entries"""
        for _i in range(0, self._read_int(fp) or 0):
            self._read_entry(fp)

    def _read_entry(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Read in an individual entry and append it to the entries stack"""
        dump_id = self._read_int(fp)
        had_dumper = bool(self._read_int(fp))
        table_oid = self._read_bytes(fp).decode(self.encoding)
        oid = self._read_bytes(fp).decode(self.encoding)
        tag = self._read_bytes(fp).decode(self.encoding)
        desc = self._read_bytes(fp).decode(self.encoding)
        self._read_int(fp)  # Section is mapped, no need to assign
        defn = self._read_bytes(fp).decode(self.encoding)
        drop_stmt = self._read_bytes(fp).decode(self.encoding)
        copy_stmt = self._read_bytes(fp).decode(self.encoding)
        namespace = self._read_bytes(fp).decode(self.encoding)
        tablespace = self._read_bytes(fp).decode(self.encoding)
        if self.version >= (1, 14, 0):
            tableam = self._read_bytes(fp).decode(self.encoding)
        else:
            tableam = ''
        owner = self._read_bytes(fp).decode(self.encoding)
        with_oids = self._read_bytes(fp) == b'true'
        dependencies = self._read_dependencies(fp)
        data_state, offset = self._read_offset(fp)
        self.entries.append(Entry(
            dump_id=dump_id, had_dumper=had_dumper, table_oid=table_oid,
            oid=oid, tag=tag, desc=desc, defn=defn, drop_stmt=drop_stmt,
            copy_stmt=copy_stmt, namespace=namespace, tablespace=tablespace,
            tableam=tableam, owner=owner, with_oids=with_oids,
            dependencies=dependencies, data_state=data_state or 0,
            offset=offset or 0))

    def _read_header(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Read in the dump header

        :raises: ValueError

        """
        if fp.read(5) != constants.MAGIC:
            raise ValueError('Invalid archive header')
        self._vmaj = struct.unpack('B', fp.read(1))[0]
        self._vmin = struct.unpack('B', fp.read(1))[0]
        self._vrev = struct.unpack('B', fp.read(1))[0]
        self._intsize = struct.unpack('B', fp.read(1))[0]
        self._offsize = struct.unpack('B', fp.read(1))[0]
        self._format = constants.FORMATS[struct.unpack(
            'B', fp.read(1))[0]]
        LOGGER.debug('Archive version %i.%i.%i',
                     self._vmaj, self._vmin, self._vrev)

    def _read_int(self, fp: typing.BinaryIO) -> typing.Optional[int]:
        """Read in a signed integer

        :rtype: int or None

        """
        sign = self._read_byte(fp)
        if sign is None:
            return None
        bs, bv, value = 0, 0, 0
        for _offset in range(0, self._intsize):
            bv = (self._read_byte(fp) or 0) & 0xFF
            if bv != 0:
                value += (bv << bs)
            bs += 8
        return -value if sign else value

    def _read_offset(self, fp: typing.BinaryIO) -> typing.Tuple[int, int]:
        """Read in the value for the length of the data stored in the file

        :rtype: int, int

        """
        data_state = self._read_byte(fp) or 0
        value = 0
        for offset in range(0, self._offsize):
            bv = self._read_byte(fp) or 0
            value |= bv << (offset * 8)
        return data_state, value

    def _read_table_data(self, dump_id: int) \
        -> typing.Generator[str, None, None]:
        """Iterate through the data returning on row at a time

        :rtype: str

        """
        try:
            with self._tempfile(dump_id, 'rb') as handle:
                for line in handle:
                    out = (line or b'').decode(self.encoding).strip()
                    if out.startswith('\\.') or not out:
                        break
                    yield out
        except exceptions.NoDataError:
            pass

    def _read_timestamp(self, fp: typing.BinaryIO) -> datetime.datetime:
        """Read in the timestamp from handle.

        :rtype: datetime.datetime

        """
        second, minute, hour, day, month, year = (
            self._read_int(fp), self._read_int(fp), self._read_int(fp),
            self._read_int(fp), (self._read_int(fp) or 0) + 1,
            (self._read_int(fp) or 0) + 1900)
        self._read_int(fp)  # DST flag
        return datetime.datetime(year, month, day, hour, minute, second, 0)

    def _save(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Save the dump file to disk"""
        self._write_toc(fp)
        self._write_entries(fp)
        if self._write_data(fp):
            self._write_toc(fp)  # Overwrite ToC and entries
            self._write_entries(fp)

    def _set_encoding(self) -> typing.NoReturn:
        """If the encoding is found in the dump entries, set the encoding
        to `self.encoding`.

        """
        for entry in self.entries:
            if entry.desc == constants.ENCODING:
                match = ENCODING_PATTERN.match(entry.defn)
                if match:
                    self.encoding = match.group(1)
                    return

    @contextlib.contextmanager
    def _tempfile(self, dump_id: int, mode: str) \
        -> typing.Generator[typing.IO[bytes], None, None]:
        """Open the temp file for the specified dump_id in the specified mode

        :param int dump_id: The dump_id for the temp file
        :param str mode: The mode (rb, wb)

        """
        path = pathlib.Path(self._temp_dir.name) / '{}.gz'.format(dump_id)
        if not path.exists() and mode.startswith('r'):
            raise exceptions.NoDataError()
        with gzip.open(path, mode) as handle:
            try:
                yield handle
            finally:
                return

    def _write_blobs(self, fp: typing.BinaryIO, dump_id: int) -> int:
        """Write the blobs for the entry.

        :param int dump_id: The entry dump ID for the blobs
        :rtype: int

        """
        with self._tempfile(dump_id, 'rb') as handle:
            fp.write(constants.BLK_BLOBS)
            self._write_int(fp, dump_id)
            while True:
                try:
                    oid = struct.unpack('I', handle.read(4))[0]
                except struct.error:
                    break
                length = struct.unpack('I', handle.read(4))[0]
                self._write_int(fp, oid)
                self._write_int(fp, length)
                fp.write(handle.read(length))
                self._write_int(fp, 0)
            self._write_int(fp, 0)
        return length

    def _write_byte(self, fp: typing.BinaryIO, value: int) -> typing.NoReturn:
        """Write a byte to the handle

        :param int value: The byte value

        """
        fp.write(struct.pack('B', value))

    def _write_data(self, fp: typing.BinaryIO) -> set:
        """Write the data blocks, returning a set of IDs that were written"""
        saved = set({})
        for offset, entry in enumerate(self.entries):
            if entry.section != constants.SECTION_DATA:
                continue
            self.entries[offset].offset = fp.tell()
            size = 0
            if entry.desc == constants.TABLE_DATA:
                size = self._write_table_data(fp, entry.dump_id)
                saved.add(entry.dump_id)
            elif entry.desc == constants.BLOBS:
                size = self._write_blobs(fp, entry.dump_id)
                saved.add(entry.dump_id)
            if size:
                self.entries[offset].data_state = constants.K_OFFSET_POS_SET
        return saved

    def _write_entries(self, fp: typing.BinaryIO):
        self._write_int(fp, len(self.entries))
        saved = set({})

        # Always add these entries first
        for entry in self.entries[0:3]:
            self._write_entry(fp, entry)
            saved.add(entry.dump_id)

        saved = self._write_section(
            fp,
            constants.SECTION_PRE_DATA, [
                constants.GROUP,
                constants.ROLE,
                constants.USER,
                constants.SCHEMA,
                constants.EXTENSION,
                constants.AGGREGATE,
                constants.OPERATOR,
                constants.OPERATOR_CLASS,
                constants.CAST,
                constants.COLLATION,
                constants.CONVERSION,
                constants.PROCEDURAL_LANGUAGE,
                constants.FOREIGN_DATA_WRAPPER,
                constants.FOREIGN_SERVER,
                constants.SERVER,
                constants.DOMAIN,
                constants.TYPE,
                constants.SHELL_TYPE], saved)

        saved = self._write_section(fp, constants.SECTION_DATA, [], saved)

        saved = self._write_section(
            fp,
            constants.SECTION_POST_DATA, [
                constants.CHECK_CONSTRAINT,
                constants.CONSTRAINT,
                constants.INDEX], saved)

        saved = self._write_section(fp, constants.SECTION_NONE, [], saved)
        LOGGER.debug('Wrote %i of %i entries', len(saved), len(self.entries))

    def _write_entry(self, fp: typing.BinaryIO, entry: 'Entry') -> typing.NoReturn:
        """Write the entry

        :param pgdumplib.dump.Entry entry: The entry to write

        """
        LOGGER.debug('Writing %r', entry)
        self._write_int(fp, entry.dump_id)
        self._write_int(fp, int(entry.had_dumper))
        self._write_str(fp, entry.table_oid or '0')
        self._write_str(fp, entry.oid or '0')
        self._write_str(fp, entry.tag)
        self._write_str(fp, entry.desc)
        self._write_int(fp, constants.SECTIONS.index(entry.section) + 1)
        self._write_str(fp, entry.defn)
        self._write_str(fp, entry.drop_stmt)
        self._write_str(fp, entry.copy_stmt)
        self._write_str(fp, entry.namespace)
        self._write_str(fp, entry.tablespace)
        if self.version >= (1, 14, 0):
            LOGGER.debug('Adding tableam')
            self._write_str(fp, entry.tableam)
        self._write_str(fp, entry.owner)
        self._write_str(fp, 'true' if entry.with_oids else 'false')
        for dependency in entry.dependencies or []:
            self._write_str(fp, str(dependency))
        self._write_int(fp, -1)
        self._write_offset(fp, entry.offset, entry.data_state)

    def _write_header(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Write the file header"""
        LOGGER.debug('Writing archive version %i.%i.%i',
                     self._vmaj, self._vmin, self._vrev)
        fp.write(constants.MAGIC)
        self._write_byte(fp, self._vmaj)
        self._write_byte(fp, self._vmin)
        self._write_byte(fp, self._vrev)
        self._write_byte(fp, self._intsize)
        self._write_byte(fp, self._offsize)
        self._write_byte(fp, constants.FORMATS.index(self._format))

    def _write_int(self, fp: typing.BinaryIO, value: int) -> typing.NoReturn:
        """Write an integer value

        :param int value:

        """
        self._write_byte(fp, 1 if value < 0 else 0)
        if value < 0:
            value = -value
        for _offset in range(0, self._intsize):
            self._write_byte(fp, value & 0xFF)
            value >>= 8

    def _write_offset(self, fp: typing.BinaryIO, value: int, data_state: int) -> typing.NoReturn:
        """Write the offset value.

        :param int value: The value to write
        :param int data_state: The data state flag

        """
        self._write_byte(fp, data_state)
        for offset in range(0, self._offsize):
            self._write_byte(fp, value & 0xFF)
            value >>= 8

    def _write_section(self, fp: typing.BinaryIO, section: str, obj_types: list, saved: set) -> set:
        for obj_type in obj_types:
            for entry in [e for e in self.entries if e.desc == obj_type]:
                self._write_entry(fp, entry)
                saved.add(entry.dump_id)
        for dump_id in toposort.toposort_flatten(
            {e.dump_id: set(e.dependencies) for e in self.entries
             if e.section == section}, True):
            if dump_id not in saved:
                self._write_entry(fp, self.get_entry(dump_id))
                saved.add(dump_id)
        return saved

    def _write_str(self, fp: typing.BinaryIO, value: str) -> typing.NoReturn:
        """Write a string

        :param str value: The string to write

        """
        out = value.encode(self.encoding) if value else b''
        self._write_int(fp, len(out))
        if out:
            LOGGER.debug('Writing %r', out)
            fp.write(out)

    def _write_table_data(self, fp: typing.BinaryIO, dump_id: int) -> int:
        """Write the blobs for the entry, returning the # of bytes written

        :param int dump_id: The entry dump ID for the blobs
        :rtype: int

        """
        fp.write(constants.BLK_DATA)
        self._write_int(fp, dump_id)

        writer = [w for w in self._writers.values() if w.dump_id == dump_id]
        if writer:  # Data was added ad-hoc
            writer[0].finish()
            self._write_int(fp, writer[0].size)
            fp.write(writer[0].read())
            self._write_int(fp, 0)  # End of data indicator
            return writer[0].size

        # Data was cached on load
        with self._tempfile(dump_id, 'rb') as handle:
            handle.seek(0, io.SEEK_END)  # Seek to end to figure out size
            size = handle.tell()
            self._write_int(fp, size)
            if size:
                handle.seek(0)  # Rewind to read data
                fp.write(handle.read())
        self._write_int(fp, 0)  # End of data indicator
        return size

    def _write_timestamp(self, fp: typing.BinaryIO, value: datetime.datetime) -> typing.NoReturn:
        """Write a datetime.datetime value

        :param datetime.datetime value: The value to write

        """
        self._write_int(fp, value.second)
        self._write_int(fp, value.minute)
        self._write_int(fp, value.hour)
        self._write_int(fp, value.day)
        self._write_int(fp, value.month - 1)
        self._write_int(fp, value.year - 1900)
        self._write_int(fp, 1 if value.dst() else 0)

    def _write_toc(self, fp: typing.BinaryIO) -> typing.NoReturn:
        """Write the ToC for the file"""
        fp.seek(0)
        self._write_header(fp)
        self._write_int(fp, int(self.compression))
        self._write_timestamp(fp, self.timestamp)
        self._write_str(fp, self.dbname)
        self._write_str(fp, self.server_version)
        self._write_str(fp, self.dump_version)


@dataclasses.dataclass(eq=True)
class Entry:
    """The entry model represents a single entry in the dataclass

    Custom formatted dump files are primarily comprised of entries, which
    contain all of the metadata and DDL required to construct the database.

    For table data and blobs, there are entries that contain offset locations
    in the dump file that instruct the reader as to where the data lives
    in the file.

    :var int dump_id: The dump id, will be auto-calculated if left empty
    :var bool had_dumper: Indicates
    :var str oid: The OID of the object the entry represents
    :var str tag: The name/table/relation/etc of the entry
    :var str desc: The entry description
    :var str defn: The DDL definition for the entry
    :var str drop_stmt: A drop statement used to drop the entry before
    :var str copy_stmt: A copy statement used when there is a corresponding
        data section.
    :var str namespace: The namespace of the entry
    :var str tablespace: The tablespace to use
    :var str tableam: The table access method
    :var str owner: The owner of the object in Postgres
    :var bool with_oids: Indicates ...
    :var list dependencies: A list of dump_ids of objects that the entry
        is dependent upon.
    :var int data_state: Indicates if the entry has data and how it is stored
    :var int offset: If the entry has data, the offset to the data in the file
    :var str section: The section of the dump file the entry belongs to

    """
    dump_id: int
    had_dumper: bool = False
    table_oid: str = '0'
    oid: str = '0'
    tag: typing.Optional[str] = None
    desc: typing.Optional[str] = None
    defn: typing.Optional[str] = None
    drop_stmt: typing.Optional[str] = None
    copy_stmt: typing.Optional[str] = None
    namespace: typing.Optional[str] = None
    tablespace: typing.Optional[str] = None
    tableam: typing.Optional[str] = None
    owner: typing.Optional[str] = None
    with_oids: bool = False
    dependencies: typing.List[int] = dataclasses.field(default_factory=list)
    data_state: int = constants.K_OFFSET_NO_DATA
    offset: int = 0

    @property
    def section(self) -> str:
        """Return the section the entry belongs to"""
        return constants.SECTION_MAPPING[self.desc]


class TableData:
    """Used to encapsulate table data using temporary file and allowing
    for an API that allows for the appending of data one row at a time.

    Do not create this class directly, instead invoke
    :py:meth:`~pgdumplib.dump.Dump.table_data_writer`.

    """

    def __init__(self, dump_id: int, tempdir: str, encoding: str):
        self.dump_id = dump_id
        self._encoding = encoding
        self._path = pathlib.Path(tempdir) / '{}.gz'.format(dump_id)
        self._handle = gzip.open(self._path, 'wb')

    def append(self, *args) -> typing.NoReturn:
        """Append a row to the table data, passing columns in as args

        Column order must match the order specified when
        :py:meth:`~pgdumplib.dump.Dump.table_data_writer` was invoked.

        All columns will be coerced to a string with special attention
        paid to ``None``, converting it to the null marker (``\\N``) and
        :py:class:`datetime.datetime` objects, which will have the proper
        pg_dump timestamp format applied to them.

        """
        row = '\t'.join([self._convert(c) for c in args])
        self._handle.write('{}\n'.format(row).encode(self._encoding))

    def finish(self) -> typing.NoReturn:
        """Invoked prior to saving a dump to close the temporary data
        handle and switch the class into read-only mode.

        For use by :py:class:`pgdumplib.dump.Dump` only.

        """
        if not self._handle.closed:
            self._handle.close()
        self._handle = gzip.open(self._path, 'rb')

    def read(self) -> bytes:
        """Read the data from disk for writing to the dump

        For use by :py:class:`pgdumplib.dump.Dump` only.

        :rtype: bytes

        """
        self._handle.seek(0)
        return self._handle.read()

    @property
    def size(self) -> int:
        """Return the current size of the data on disk

        :rtype: int

        """
        self._handle.seek(0, io.SEEK_END)  # Seek to end to figure out size
        size = self._handle.tell()
        self._handle.seek(0)
        return size

    @staticmethod
    def _convert(column: typing.Any) -> str:
        """Convert the column to a string

        :param any column: The column to convert

        """
        if isinstance(column, datetime.datetime):
            return column.strftime(constants.PGDUMP_STRFTIME_FMT)
        elif column is None:
            return '\\N'
        return str(column)
