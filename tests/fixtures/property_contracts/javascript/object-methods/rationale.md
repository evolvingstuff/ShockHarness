# Methods of object literals are their own units

From MetaList on 0.10.0: with the family enabled, `shockharness check` failed with
`KeyError: 'document'`. The flow evaluated an object literal by walking into its methods'
bodies, while the unit's names are collected without entering them, so a name only a
method reads (`document`, a method's parameter `controller`) was not in the entry state.

- `Tracker.start` and the `ReadableStream` source's `start(controller)` are analyzed with
  no finding and no failure.
- `Tracker.show` is checked as a unit of its own: `deliver(raw)` is PROP001.
