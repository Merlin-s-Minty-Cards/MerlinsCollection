"""Slab (graded card) services — RFC 0009.

``pricing`` is the per-grade market-value provider; ``quota`` is the outbound
call budget both it and (eventually) the PSA cert lookup spend from.

The PSA half of RFC 0009 (T2) is DEFERRED — the account is not approved for the
public API and every call returns ``403``, so there is nothing to map. This
package therefore ships with pricing only, and ``quota`` was written here rather
than in T2 as originally planned.
"""
