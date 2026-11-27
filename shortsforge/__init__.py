"""
__init__.py - marks this folder as a Python "package".

WHY it exists:
    Python only lets you write `from shortsforge import x` if the folder has this file.
HOW it works:
    Python runs this file once when the package is first imported.
HOW TO IMPROVE:
    Bump __version__ every time you change something, and write the change in PROJECT.md.
"""

# A version number so you always know which build you are running.
__version__ = "0.9.0"
