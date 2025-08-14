#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Interfaces for refine components to support dependency injection and testing.
"""

from abc import ABC, abstractmethod
from typing import List, Tuple

from .segment import Segment, CharClassSegment


class IRegexParser(ABC):
    """Interface for regex pattern parsing."""
    
    @abstractmethod
    def parse(self, pattern: str) -> List[Segment]:
        """Parse regex pattern into segments."""
        pass


class ISplittabilityAnalyzer(ABC):
    """Interface for pattern splittability analysis."""
    
    @abstractmethod
    def can_split_further(
        self, 
        pattern: str, 
        segments: List[Segment], 
        current_depth: int = 0
    ) -> Tuple[bool, str]:
        """Determine if pattern can be split further."""
        pass


class IEnumerationOptimizer(ABC):
    """Interface for enumeration strategy optimization."""
    
    @abstractmethod
    def optimize(self, segments: List[Segment], partitions: int = 10):
        """Optimize enumeration strategy for given segments."""
        pass


class IQueryGenerator(ABC):
    """Interface for query generation."""
    
    @abstractmethod
    def generate(self, strategy, max_depth: int = 3) -> List[str]:
        """Generate queries from enumeration strategy."""
        pass
