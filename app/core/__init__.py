"""Core package marker for Native Flow.

Source ``app/core/__init__.py`` imports the monolith ``Config`` class
and re-exports ``config_manager``. Native Flow imports
``app.core.security``, ``app.core.context``, and
``app.core.config`` directly. This marker avoids
loading the product-wide config module.
"""
