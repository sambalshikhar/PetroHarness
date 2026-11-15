"""The evidence graph: what an answer rests on, as data that can be walked from a sentence back to the LAS file.

    record   the computation graph as the well's record holds it: curves, the steps that computed them, what each
             step read, its parameters (a snapshot kept in the session log)
    links    which results show each number an answer states (the number checker's own matching, result by result)
    graph    the evidence graph of a conversation, rebuilt from its log: the LAS file, curves, steps, results, claims,
             answers and figures, and the links between them
    audit    the audit trail of an answer, written from the graph

Nothing here reaches a prompt: the graph is read off a conversation's record, so it cannot change an answer.
docs/EVIDENCE.md.
"""
from petroharness.evidence.graph import EvidenceGraph  # noqa: F401
