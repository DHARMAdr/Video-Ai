"""
localsearch - ShortsForge's own web search, used when you have no Tavily key.

query.py   understands the question and makes a few ways to ask it
sources.py asks several free search services and reads their answers
rank.py    mixes the lists and picks the best paragraphs
engine.py  runs the steps in order, in parallel, with a time limit

It is NOT a search index of the whole internet: it asks other services, so it works only
as well as they answer, and they may refuse a program that asks too often.
"""

from .engine import search

__all__ = ["search"]
