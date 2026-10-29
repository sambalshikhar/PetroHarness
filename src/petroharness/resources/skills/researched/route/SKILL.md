---
name: route
when: how a curve or class the answer uses was computed, its model, inputs and parameters
areas: []
---

# route

## Consider
- Is the curve in the raw input (the LAS as given) or computed by a workflow step? The map says which.
- For a computed curve, which method, inputs and parameters did its step record, and which of them were defaults?

## Compare
- step NAME
- stats CURVE

## Decide
- Name the model and parameters a computed curve used, with their source (a default, the LAS, computed); a default is a model choice, not a measurement.

## Know
- A curve in the raw input means what its name says regardless of where it came from (PHIE_CC is core-calibrated porosity, PERM_CC core-calibrated permeability).
- A step's parameters with a _source field say where each value came from (config, the LAS, computed).

## Easily misread
- Two curves that one step computed from each other, or from one input, move together because of the arithmetic.

## Do not state
- Core-measured or sampled parameters where the record shows defaults or a computed route; results of a model the workflow did not run, given as computed values.
