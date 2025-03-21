#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from charm import flatten_config


@pytest.mark.parametrize(
    "data, prefix, expected",
    [
        # Flat dictionary with a prefix
        (
            {"a": "value1", "b": "value2"},
            "provider[0]",
            {
                "provider[0].a": "value1",
                "provider[0].b": "value2",
            },
        ),
        # Nested dictionary with a prefix
        (
            {"a": {"b": 1, "c": {"d": "x"}}, "e": 2},
            "prefix",
            {
                "prefix.a.b": 1,
                "prefix.a.c.d": "x",
                "prefix.e": 2,
            },
        ),
        # Empty dictionary returns an empty dictionary
        ({}, "p", {}),
        # Dictionary with list values; each list item gets an index
        (
            {"a": 1, "b": ["1", "2", "3"], "c": ["1", "2"]},
            "provider[1]",
            {
                "provider[1].a": 1,
                "provider[1].b[0]": "1",
                "provider[1].b[1]": "2",
                "provider[1].b[2]": "3",
                "provider[1].c[0]": "1",
                "provider[1].c[1]": "2",
            },
        ),
        # Dictionary with tuple values; each tuple item gets an index
        (
            {"x": (10, 20), "y": ("a", "b", "c")},
            "provider",
            {
                "provider.x[0]": 10,
                "provider.x[1]": 20,
                "provider.y[0]": "a",
                "provider.y[1]": "b",
                "provider.y[2]": "c",
            },
        ),
        # Flat data structure with an empty prefix produces keys without a leading dot
        (
            {"a": 1, "b": ["1", "2", "3"], "c": ["1", "2"]},
            "",
            {
                "a": 1,
                "b[0]": "1",
                "b[1]": "2",
                "b[2]": "3",
                "c[0]": "1",
                "c[1]": "2",
            },
        ),
        # Nested data structure with an empty prefix produces keys without a leading dot
        (
            {"a": {"b": 1}, "c": ["1", "2", "3"], "d": {"e": ["1", "2", "3"]}},
            "",
            {
                "a.b": 1,
                "c[0]": "1",
                "c[1]": "2",
                "c[2]": "3",
                "d.e[0]": "1",
                "d.e[1]": "2",
                "d.e[2]": "3",
            },
        ),
        # Primitive value with a prefix
        (42, "number", {"number": 42}),
        # Primitive value with an empty prefix returns a dict with an empty key
        ("primitive", "", {"": "primitive"}),
    ],
)
def test_flatten_config(data, prefix, expected):
    """Parameterized tests for the flatten_config function."""
    result = flatten_config(data, prefix)
    assert result == expected
