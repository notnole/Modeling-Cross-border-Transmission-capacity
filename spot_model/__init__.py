"""spot_model — cross-border transmission capacity valuation (Margrabe spread).

Single source of truth for the model. Submodules:
  - loader         : data access (spot.csv, live ENTSO-E DA prices, JAO auction
                     clearing prices, forward-product helpers).
  - delivery_class : base / peak / offpeak hour masks.
  - border_class   : DataBorderClass — loads spot history, computes per-hour
                     implicit value, aggregates by delivery profile.
  - capacity_class : Capacity / ImplicitCapacity — fits sigma and prices the
                     Margrabe spread option; CapacityDict aggregates borders.

Runnable examples live in ../examples.
"""
