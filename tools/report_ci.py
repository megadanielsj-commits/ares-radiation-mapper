#!/usr/bin/env python3
"""Expose actual pytest failures as GitHub annotations from a JUnit report."""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


def escape(value, *, property_value=False):
    value = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    return value.replace(',', '%2C') if property_value else value


def report(path):
    path = Path(path)
    if not path.is_file():
        print('::notice::No pytest report was generated; check the installation/test step.')
        return
    root = ET.parse(path).getroot()
    failures = 0
    for case in root.iter('testcase'):
        for tag in ('failure', 'error'):
            result = case.find(tag)
            if result is None:
                continue
            failures += 1
            title = 'pytest: ' + '.'.join(filter(None, [case.get('classname'), case.get('name')]))
            detail = result.text or result.get('message') or tag
            # Keep tracebacks readable in the public check annotations.
            print(f'::error title={escape(title, property_value=True)}::{escape(detail[-6000:])}')
    print(f'::notice::Pytest report contains {failures} failure/error entries.')


if __name__ == '__main__':
    report(sys.argv[1] if len(sys.argv) > 1 else 'pytest-results.xml')
