"""Step-record parameters: which are bookkeeping, not settings a reader uses (one list for the map, the step tool and
the inventory)."""

# where a value came from, requested vs used, sample tallies, metadata, the methods tried
BOOKKEEPING = ("_source", "_requested", "_count", "_counts", "_samples", "_reason", "_basis", "_metadata", "_sources",
               "_attempted_methods", "_rejected_models", "_used")
# a range that repeats a curve's own statistics: the map leaves it out, the step tool shows it
RANGES = ("_min", "_max")
