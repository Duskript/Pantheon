"""
sources/ — per-source connector implementations.

Each subdirectory is a connector for a single external content source
(YouTube Takeout, Gmail, RSS, Claude export, etc.). All connectors
inherit from ``lib.base.ConnectorBase`` and follow the same
authenticate → fetch → normalize → drop-in-inbox contract.

See ``connectors/README.md`` for the connector contract and
``lib/base.py`` for the base class.
"""
