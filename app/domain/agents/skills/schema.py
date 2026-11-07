"""Strict JSON Schema for skill.json (additionalProperties=false)."""

from __future__ import annotations

SKILL_METADATA_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "id",
        "version",
        "description",
        "allowed_tools",
        "required_tools",
        "resources",
    ],
    "properties": {
        "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z][a-z0-9-]*$",
        },
        "version": {
            "type": "string",
            "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
        },
        "description": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
        },
        "allowed_tools": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": "^[a-z][a-z0-9_]*$",
            },
        },
        "required_tools": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": "^[a-z][a-z0-9_]*$",
            },
        },
        "resources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "path"],
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                        "pattern": "^[a-z][a-z0-9_-]*$",
                    },
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                },
            },
        },
    },
}
