"""Test file with intentional errors for auto-fix testing."""

import os
import sys
import json  # unused import - lint error

def calculate_sum(a, b)  # missing colon - syntax error
    return a + b

def unused_function():
    x = 1
    y = 2
    # x and y are unused - lint error
    pass

class badClassName:  # should be BadClassName - naming convention error
    def __init__(self):
        self.value = 1
