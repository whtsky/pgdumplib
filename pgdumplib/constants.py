"""
Constants used in the reading and writing of a :command:`pg_dump` file.
There are additional undocumented constants, but they should not be of concern
unless you are hacking on the library itself.

"""
import typing

APPEAR_AS: str = '12.0'
"""Version of PostgreSQL to appear as"""

BLK_DATA: bytes = b'\x01'
BLK_BLOBS: bytes = b'\x03'

EOF: int = -1

FORMAT_UNKNOWN: int = 0
FORMAT_CUSTOM: int = 1
FORMAT_FILES: int = 2
FORMAT_TAR: int = 3
FORMAT_NULL: int = 4
FORMAT_DIRECTORY: int = 5

FORMATS: typing.List[str] = [
    'Unknown',
    'Custom',
    'Files',
    'Tar',
    'Null',
    'Directory'
]

K_OFFSET_POS_NOT_SET: int = 1
"""Specifies the entry has data but no offset"""
K_OFFSET_POS_SET: int = 2
"""Specifies the entry has data and an offset"""
K_OFFSET_NO_DATA: int = 3
"""Specifies the entry has no data"""

MAGIC: bytes = b'PGDMP'

MIN_VER: typing.Tuple[int, int, int] = (1, 13, 0)
"""The minumum supported version of pg_dump files ot support"""

MAX_VER: typing.Tuple[int, int, int] = (1, 14, 0)
"""The maximum supported version of pg_dump files ot support"""

PGDUMP_STRFTIME_FMT: str = '%Y-%m-%d %H:%M:%S %Z'

SECTION_NONE: str = 'None'
"""Non-specific section for an entry in a dump's table of contents"""

SECTION_PRE_DATA: str = 'Pre-Data'
"""Pre-data section for an entry in a dump's table of contents"""

SECTION_DATA: str = 'DATA'
"""Data section for an entry in a dump's table of contents"""

SECTION_POST_DATA: str = 'Post-Data'
"""Post-data section for an entry in a dump's table of contents"""

SECTIONS: typing.List[str] = [
    SECTION_NONE,
    SECTION_PRE_DATA,
    SECTION_DATA,
    SECTION_POST_DATA
]

VERSION: typing.Tuple[int, int, int] = (1, 14, 0)
"""pg_dump file format version to create by default"""

ZLIB_OUT_SIZE: int = 4096
ZLIB_IN_SIZE: int = 4096

# Object Types

ACCESS_METHOD: str = 'ACCESS METHOD'
ACL: str = 'ACL'
AGGREGATE: str = 'AGGREGATE'
BLOB: str = 'BLOB'
BLOBS: str = 'BLOBS'
CAST: str = 'CAST'
CHECK_CONSTRAINT: str = 'CHECK CONSTRAINT'
COLLATION: str = 'COLLATION'
COMMENT: str = 'COMMENT'
CONSTRAINT: str = 'CONSTRAINT'
CONVERSION: str = 'CONVERSION'
DATABASE: str = 'DATABASE'
DATABASE_PROPERTIES: str = 'DATABASE PROPERTIES'
DEFAULT: str = 'DEFAULT'
DEFAULT_ACL: str = 'DEFAULT ACL'
DOMAIN: str = 'DOMAIN'
ENCODING: str = 'ENCODING'
EVENT_TRIGGER: str = 'EVENT TRIGGER'
EXTENSION: str = 'EXTENSION'
FK_CONSTRAINT: str = 'FK CONSTRAINT'
FOREIGN_DATA_WRAPPER: str = 'FOREIGN DATA WRAPPER'
FOREIGN_SERVER: str = 'FOREIGN SERVER'
FOREIGN_TABLE: str = 'FOREIGN TABLE'
FUNCTION: str = 'FUNCTION'
GROUP: str = 'GROUP'
INDEX: str = 'INDEX'
INDEX_ATTACH: str = 'INDEX ATTACH'
LARGE_OBJECT: str = 'LARGE OBJECT'
MATERIALIZED_VIEW: str = 'MATERIALIZED VIEW'
MATERIALIZED_VIEW_DATA: str = 'MATERIALIZED VIEW DATA'
OPERATOR: str = 'OPERATOR'
OPERATOR_CLASS: str = 'OPERATOR CLASS'
OPERATOR_FAMILY: str = 'OPERATOR FAMILY'
PG_LARGEOBJECT: str = 'pg_largeobject'
POLICY: str = 'POLICY'
PROCEDURE: str = 'PROCEDURE'
PROCEDURAL_LANGUAGE: str = 'PROCEDURAL LANGUAGE'
PUBLICATION: str = 'PUBLICATION'
PUBLICATION_TABLE: str = 'PUBLICATION TABLE'
ROLE: str = 'ROLE'
ROW_SECURITY: str = 'ROW SECURITY'
RULE: str = 'RULE'
SCHEMA: str = 'SCHEMA'
SEARCHPATH: str = 'SEARCHPATH'
SECURITY_LABEL: str = 'SECURITY LABEL'
SEQUENCE: str = 'SEQUENCE'
SEQUENCE_OWNED_BY: str = 'SEQUENCE OWNED BY'
SEQUENCE_SET: str = 'SEQUENCE SET'
SERVER: str = 'SERVER'
SHELL_TYPE: str = 'SHELL TYPE'
STATISTICS: str = 'STATISTICS'
STDSTRINGS: str = 'STDSTRINGS'
SUBSCRIPTION: str = 'SUBSCRIPTION'
TABLE: str = 'TABLE'
TABLE_DATA: str = 'TABLE DATA'
TABLESPACE: str = 'TABLESPACE'
TEXT_SEARCH_DICTIONARY: str = 'TEXT SEARCH DICTIONARY'
TEXT_SEARCH_CONFIGURATION: str = 'TEXT SEARCH CONFIGURATION'
TEXT_SEARCH_PARSER: str = 'TEXT SEARCH PARSER'
TEXT_SEARCH_TEMPLATE: str = 'TEXT SEARCH TEMPLATE'
TRANSFORM: str = 'TRANSFORM'
TRIGGER: str = 'TRIGGER'
TYPE: str = 'TYPE'
USER: str = 'USER'
USER_MAPPING: str = 'USER MAPPING'
VIEW: str = 'VIEW'

SECTION_MAPPING: typing.Dict[str, str] = {
    ACCESS_METHOD: SECTION_PRE_DATA,
    ACL: SECTION_NONE,
    AGGREGATE: SECTION_PRE_DATA,
    BLOB: SECTION_PRE_DATA,
    BLOBS: SECTION_DATA,
    CAST: SECTION_PRE_DATA,
    CHECK_CONSTRAINT: SECTION_POST_DATA,
    COLLATION: SECTION_PRE_DATA,
    COMMENT: SECTION_NONE,
    CONSTRAINT: SECTION_POST_DATA,
    CONVERSION: SECTION_PRE_DATA,
    DATABASE: SECTION_PRE_DATA,
    DATABASE_PROPERTIES: SECTION_PRE_DATA,
    DEFAULT: SECTION_PRE_DATA,
    DEFAULT_ACL: SECTION_POST_DATA,
    DOMAIN: SECTION_PRE_DATA,
    ENCODING: SECTION_PRE_DATA,
    EVENT_TRIGGER: SECTION_POST_DATA,
    EXTENSION: SECTION_PRE_DATA,
    FK_CONSTRAINT: SECTION_POST_DATA,
    FOREIGN_DATA_WRAPPER: SECTION_PRE_DATA,
    FOREIGN_SERVER: SECTION_NONE,
    FOREIGN_TABLE: SECTION_PRE_DATA,
    FUNCTION: SECTION_PRE_DATA,
    GROUP: SECTION_NONE,
    INDEX: SECTION_POST_DATA,
    INDEX_ATTACH: SECTION_POST_DATA,
    LARGE_OBJECT: SECTION_NONE,
    MATERIALIZED_VIEW: SECTION_POST_DATA,
    MATERIALIZED_VIEW_DATA: SECTION_POST_DATA,
    OPERATOR: SECTION_PRE_DATA,
    OPERATOR_CLASS: SECTION_PRE_DATA,
    OPERATOR_FAMILY: SECTION_PRE_DATA,
    PG_LARGEOBJECT: SECTION_PRE_DATA,
    POLICY: SECTION_POST_DATA,
    PROCEDURE: SECTION_PRE_DATA,
    PROCEDURAL_LANGUAGE: SECTION_PRE_DATA,
    PUBLICATION: SECTION_POST_DATA,
    PUBLICATION_TABLE: SECTION_POST_DATA,
    ROLE: SECTION_NONE,
    ROW_SECURITY: SECTION_POST_DATA,
    RULE: SECTION_POST_DATA,
    SCHEMA: SECTION_PRE_DATA,
    SEARCHPATH: SECTION_PRE_DATA,
    SECURITY_LABEL: SECTION_NONE,
    SERVER: SECTION_PRE_DATA,
    SEQUENCE: SECTION_PRE_DATA,
    SEQUENCE_SET: SECTION_DATA,
    SEQUENCE_OWNED_BY: SECTION_PRE_DATA,
    SHELL_TYPE: SECTION_PRE_DATA,
    STATISTICS: SECTION_POST_DATA,
    STDSTRINGS: SECTION_PRE_DATA,
    SUBSCRIPTION: SECTION_PRE_DATA,
    TABLESPACE: SECTION_PRE_DATA,  # Not part of a postgres created pg_dump
    TABLE: SECTION_PRE_DATA,
    TABLE_DATA: SECTION_DATA,
    TRANSFORM: SECTION_PRE_DATA,
    TRIGGER: SECTION_POST_DATA,
    TYPE: SECTION_PRE_DATA,
    TEXT_SEARCH_CONFIGURATION: SECTION_PRE_DATA,
    TEXT_SEARCH_DICTIONARY: SECTION_PRE_DATA,
    TEXT_SEARCH_PARSER: SECTION_PRE_DATA,
    TEXT_SEARCH_TEMPLATE: SECTION_PRE_DATA,
    USER: SECTION_NONE,
    USER_MAPPING: SECTION_PRE_DATA,
    VIEW: SECTION_PRE_DATA
}
