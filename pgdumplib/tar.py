# coding=utf-8
"""
tar
===
Implements the Dump class for tar based archives

"""
import pathlib
import tarfile

from pgdumplib import reader


class Dump(reader.Dump):
    pass


def load(filepath):
    """Load a pg_dump file created with -Ft

    :raises: `ValueError`
    :rtype: pgdumplib.models.Dump

    """
    path = pathlib.Path(filepath)
    if not path.exists():
        raise ValueError('Path {!r} does not exist'.format(path))

    if not tarfile.is_tarfile(str(path)):
        raise ValueError('Path {!r} is not a tar file'.format(path))

    with tarfile.open(path, 'r') as handle:
        tarinfo = handle.getmember('toc.dat')
        toc = handle.extractfile(tarinfo)
        return Dump(str(path), reader.ToC(toc).read())
