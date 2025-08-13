#!/usr/bin/env python3

"""
Field Mappers - Statistics Field Mapping Utilities

This module provides utilities for mapping between different statistics data structures
using configuration-driven approach to eliminate hardcoded field access.
"""

from typing import Dict, Protocol

from constant.runtime import STATS_MAPPINGS

from .models import KeyMetrics, ResourceMetrics


class StatsSource(Protocol):
    """Protocol for objects that can provide statistics fields"""

    # Fields from STATS_MAPPINGS.result_field
    valid_keys: int
    invalid_keys: int
    no_quota_keys: int
    wait_check_keys: int
    material_keys: int
    total_links: int
    inspect_count: int


class FieldMapper:
    """Maps statistics fields using configuration to eliminate hardcoded access"""

    @staticmethod
    def map_to_key_metrics(source: StatsSource) -> KeyMetrics:
        """Map source object to KeyMetrics using field configuration

        Args:
            source: Source object with statistics fields

        Returns:
            KeyMetrics object with mapped values
        """
        metrics = KeyMetrics()

        for _, mapping in STATS_MAPPINGS.items():
            if mapping.key_field:
                value = getattr(source, mapping.result_field, 0)
                setattr(metrics, mapping.key_field, value)

        return metrics

    @staticmethod
    def map_to_resource_metrics(source: StatsSource) -> ResourceMetrics:
        """Map source object to ResourceMetrics using field configuration

        Args:
            source: Source object with statistics fields

        Returns:
            ResourceMetrics object with mapped values
        """
        metrics = ResourceMetrics()

        for _, mapping in STATS_MAPPINGS.items():
            if mapping.resource_field:
                value = getattr(source, mapping.result_field, 0)
                setattr(metrics, mapping.resource_field, value)

        return metrics

    @staticmethod
    def aggregate_key_metrics(sources: Dict[str, StatsSource]) -> KeyMetrics:
        """Aggregate multiple sources into single KeyMetrics without intermediate objects

        Args:
            sources: Dictionary of source objects to aggregate

        Returns:
            Aggregated KeyMetrics object
        """
        total = KeyMetrics()

        # Direct aggregation using field mappings to avoid intermediate object creation
        for source in sources.values():
            for _, mapping in STATS_MAPPINGS.items():
                if mapping.key_field:
                    value = getattr(source, mapping.result_field, 0)
                    current_total = getattr(total, mapping.key_field, 0)
                    setattr(total, mapping.key_field, current_total + value)

        return total

    @staticmethod
    def aggregate_resource_metrics(sources: Dict[str, StatsSource]) -> ResourceMetrics:
        """Aggregate multiple sources into single ResourceMetrics without intermediate objects

        Args:
            sources: Dictionary of source objects to aggregate

        Returns:
            Aggregated ResourceMetrics object
        """
        total = ResourceMetrics()

        # Direct aggregation using field mappings to avoid intermediate object creation
        for source in sources.values():
            for _, mapping in STATS_MAPPINGS.items():
                if mapping.resource_field:
                    value = getattr(source, mapping.result_field, 0)
                    current_total = getattr(total, mapping.resource_field, 0)
                    setattr(total, mapping.resource_field, current_total + value)

        return total
